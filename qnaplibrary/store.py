"""SQLite storage: collections (databases), documents, chunks, FTS index, vectors, patents,
devices, passkeys, chat and jobs.

Low-I/O policy: one connection, WAL, synchronous=NORMAL, big page cache, temp in RAM,
mmap reads, batched transactions. Durability is kept (no journal_mode=OFF, no fsync=OFF).
"""
import hashlib
import json
import logging
import sqlite3
import threading
import time
from array import array

from . import textproc

LOG = logging.getLogger("qnaplibrary.store")
SCHEMA_VERSION = 1
KINDS = ("generic", "patent", "standard", "news", "market", "law", "paper", "note")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS collections(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, kind TEXT NOT NULL DEFAULT 'generic',
  description TEXT NOT NULL DEFAULT '', settings TEXT NOT NULL DEFAULT '{}',
  created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY, collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  ext_id TEXT, title TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
  doc_date TEXT NOT NULL DEFAULT '', meta TEXT NOT NULL DEFAULT '{}', body TEXT NOT NULL DEFAULT '',
  hash TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL,
  UNIQUE(collection_id, ext_id));
CREATE INDEX IF NOT EXISTS documents_coll ON documents(collection_id, updated);
CREATE TABLE IF NOT EXISTS chunks(
  id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  collection_id INTEGER NOT NULL, ord INTEGER NOT NULL, section TEXT NOT NULL DEFAULT '', text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS chunks_coll ON chunks(collection_id);
CREATE TABLE IF NOT EXISTS vectors(
  chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  collection_id INTEGER NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, vec BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS vectors_coll ON vectors(collection_id);
CREATE TABLE IF NOT EXISTS devices(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, scopes TEXT NOT NULL DEFAULT 'rw',
  created REAL NOT NULL, last_seen REAL, last_ip TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS passkeys(
  credential_id BLOB PRIMARY KEY, public_key BLOB NOT NULL, alg INTEGER NOT NULL, sign_count INTEGER NOT NULL,
  name TEXT NOT NULL DEFAULT '', created REAL NOT NULL, last_used REAL);
CREATE TABLE IF NOT EXISTS patents(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'disclosure',
  data TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS patent_events(
  id INTEGER PRIMARY KEY, patent_id INTEGER NOT NULL REFERENCES patents(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, date TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS patent_claims(
  id INTEGER PRIMARY KEY, patent_id INTEGER NOT NULL REFERENCES patents(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, text TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS patent_refs(
  id INTEGER PRIMARY KEY, patent_id INTEGER NOT NULL REFERENCES patents(id) ON DELETE CASCADE,
  doc_id INTEGER, ref TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'A',
  relevance TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS chat_threads(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS chat_messages(
  id INTEGER PRIMARY KEY, thread_id INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, params TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
  result TEXT NOT NULL DEFAULT '', created REAL NOT NULL, finished REAL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '');
"""


def now():
    return time.time()


def _j(value):
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _uj(text):
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {}


class StoreError(ValueError):
    pass


class Store:
    def __init__(self, path, cache_mb=64):
        self.path = str(path)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        for pragma in ("journal_mode=WAL", "synchronous=NORMAL", "foreign_keys=ON", "temp_store=MEMORY",
                       "cache_size=-%d" % (cache_mb * 1024), "mmap_size=%d" % (256 * 1024 * 1024),
                       "wal_autocheckpoint=2000", "busy_timeout=30000"):
            self.db.execute("PRAGMA " + pragma)
        self.db.executescript(SCHEMA)
        self.fts = self._init_fts()
        self.vector_version = 0  # bumped on vector change; vector cache invalidation
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))

    def _init_fts(self):
        try:
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(title, tok, tokenize='unicode61 remove_diacritics 0')")
            return True
        except sqlite3.OperationalError as error:
            LOG.warning("FTS5 unavailable (%s); falling back to LIKE scans", error)
            return False

    def close(self):
        with self.lock:
            try:
                self.db.execute("PRAGMA optimize")
            finally:
                self.db.close()

    # helpers ------------------------------------------------------------
    def q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchone()

    def tx(self):
        store = self

        class _Tx:
            def __enter__(self_):
                store.lock.acquire()
                store.db.execute("BEGIN IMMEDIATE")
                return store.db

            def __exit__(self_, exc_type, exc, tb):
                try:
                    store.db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store.lock.release()
        return _Tx()

    def audit(self, actor, action, detail=""):
        with self.lock:
            self.db.execute("INSERT INTO audit(ts,actor,action,detail) VALUES(?,?,?,?)",
                            (now(), actor, action, str(detail)[:500]))
            self.db.execute("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - 2000")

    # collections --------------------------------------------------------
    def collection_row(self, row, counts=True):
        d = {"id": row["id"], "name": row["name"], "kind": row["kind"], "description": row["description"],
             "settings": _uj(row["settings"]), "created": row["created"], "updated": row["updated"]}
        if counts:
            d["documents"] = self.one("SELECT COUNT(*) FROM documents WHERE collection_id=?", (row["id"],))[0]
            d["chunks"] = self.one("SELECT COUNT(*) FROM chunks WHERE collection_id=?", (row["id"],))[0]
            d["vectors"] = self.one("SELECT COUNT(*) FROM vectors WHERE collection_id=?", (row["id"],))[0]
        return d

    def list_collections(self):
        return [self.collection_row(r) for r in self.q("SELECT * FROM collections ORDER BY name")]

    def get_collection(self, ref):
        if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
            row = self.one("SELECT * FROM collections WHERE id=?", (int(ref),))
        else:
            row = self.one("SELECT * FROM collections WHERE name=?", (str(ref),))
        if not row:
            raise StoreError("collection not found: %s" % ref)
        return self.collection_row(row)

    def create_collection(self, name, kind="generic", description="", settings=None):
        name = (name or "").strip()
        if not name or len(name) > 80:
            raise StoreError("name must be 1-80 characters")
        if kind not in KINDS:
            raise StoreError("kind must be one of %s" % ", ".join(KINDS))
        t = now()
        with self.lock:
            try:
                cur = self.db.execute("INSERT INTO collections(name,kind,description,settings,created,updated) VALUES(?,?,?,?,?,?)",
                                      (name, kind, description or "", _j(settings), t, t))
            except sqlite3.IntegrityError:
                raise StoreError("collection already exists: %s" % name)
        return self.get_collection(cur.lastrowid)

    def ensure_collection(self, name, kind="generic", description=""):
        try:
            return self.get_collection(name)
        except StoreError:
            return self.create_collection(name, kind, description)

    def update_collection(self, cid, patch):
        c = self.get_collection(cid)
        name = patch.get("name", c["name"])
        kind = patch.get("kind", c["kind"])
        if kind not in KINDS:
            raise StoreError("invalid kind")
        with self.lock:
            self.db.execute("UPDATE collections SET name=?,kind=?,description=?,settings=?,updated=? WHERE id=?",
                            (name, kind, patch.get("description", c["description"]),
                             _j(patch.get("settings", c["settings"])), now(), c["id"]))
        return self.get_collection(c["id"])

    def delete_collection(self, cid):
        c = self.get_collection(cid)
        with self.tx() as db:
            if self.fts:
                db.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE collection_id=?)", (c["id"],))
            db.execute("DELETE FROM vectors WHERE collection_id=?", (c["id"],))
            db.execute("DELETE FROM chunks WHERE collection_id=?", (c["id"],))
            db.execute("DELETE FROM documents WHERE collection_id=?", (c["id"],))
            db.execute("DELETE FROM collections WHERE id=?", (c["id"],))
        self.vector_version += 1
        return c

    # documents ----------------------------------------------------------
    @staticmethod
    def _sections(doc, kind):
        """Return [(section, text)] to chunk. Patent claims are split one claim per chunk."""
        out = []
        body = doc.get("body") or ""
        sections = doc.get("sections")
        if isinstance(sections, dict):
            for name, text in sections.items():
                if not text:
                    continue
                if name in ("claims", "請求の範囲", "特許請求の範囲"):
                    for n, ctext in textproc.split_claims(str(text)):
                        out.append(("claim %d" % n, ctext))
                else:
                    out.extend((str(name), c) for c in textproc.chunk_text(str(text)))
        if body:
            if kind == "patent" and "【請求項" in body and not sections:
                for n, ctext in textproc.split_claims(body):
                    out.append(("claim %d" % n, ctext))
            else:
                out.extend(("body", c) for c in textproc.chunk_text(body))
        abstract = doc.get("abstract")
        if abstract:
            out.insert(0, ("abstract", str(abstract)[:4000]))
        if not out and doc.get("title"):
            out.append(("title", str(doc["title"])))
        return out

    def add_documents(self, cid, docs, actor="system"):
        """Insert or replace documents (by ext_id). Returns counts. One transaction per call."""
        c = self.get_collection(cid)
        if not isinstance(docs, list):
            raise StoreError("documents must be a list")
        if len(docs) > 5000:
            raise StoreError("max 5000 documents per request")
        added = updated = unchanged = 0
        ids = []
        t = now()
        with self.tx() as db:
            for doc in docs:
                if not isinstance(doc, dict):
                    raise StoreError("each document must be an object")
                title = str(doc.get("title") or "")[:1000]
                body = str(doc.get("body") or "")
                meta = dict(doc.get("meta")) if isinstance(doc.get("meta"), dict) else {}
                if doc.get("abstract"):
                    meta["abstract"] = str(doc["abstract"])[:4000]
                sections = doc.get("sections") if isinstance(doc.get("sections"), dict) else None
                if sections and not body:
                    body_view = "\n\n".join("【%s】\n%s" % (k, v) for k, v in sections.items() if v)
                else:
                    body_view = body
                if len(body_view) > 20_000_000:
                    raise StoreError("document too large (max 20MB text)")
                ext_id = str(doc.get("id") or doc.get("ext_id") or "") or None
                digest = hashlib.sha256(json.dumps([title, body_view, meta, doc.get("url"), doc.get("date")],
                                                   ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                row = db.execute("SELECT id, hash FROM documents WHERE collection_id=? AND ext_id=?",
                                 (c["id"], ext_id)).fetchone() if ext_id else None
                if row and row["hash"] == digest:
                    unchanged += 1
                    ids.append(row["id"])
                    continue
                if row:
                    doc_id = row["id"]
                    self._drop_chunks(db, doc_id)
                    db.execute("UPDATE documents SET title=?,url=?,source=?,doc_date=?,meta=?,body=?,hash=?,updated=? WHERE id=?",
                               (title, str(doc.get("url") or ""), str(doc.get("source") or ""), str(doc.get("date") or ""),
                                _j(meta), body_view, digest, t, doc_id))
                    updated += 1
                else:
                    cur = db.execute("INSERT INTO documents(collection_id,ext_id,title,url,source,doc_date,meta,body,hash,created,updated)"
                                     " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                                     (c["id"], ext_id, title, str(doc.get("url") or ""), str(doc.get("source") or ""),
                                      str(doc.get("date") or ""), _j(meta), body_view, digest, t, t))
                    doc_id = cur.lastrowid
                    added += 1
                ids.append(doc_id)
                title_tok = textproc.index_text(title)
                for ord_, (section, text) in enumerate(self._sections(doc, c["kind"])):
                    cur = db.execute("INSERT INTO chunks(doc_id,collection_id,ord,section,text) VALUES(?,?,?,?,?)",
                                     (doc_id, c["id"], ord_, section, text))
                    if self.fts:
                        db.execute("INSERT INTO chunks_fts(rowid,title,tok) VALUES(?,?,?)",
                                   (cur.lastrowid, title_tok, textproc.index_text(section + " " + text)))
            db.execute("UPDATE collections SET updated=? WHERE id=?", (t, c["id"]))
        if added or updated:
            self.vector_version += 1
            self.audit(actor, "documents.add", "%s +%d ~%d" % (c["name"], added, updated))
        return {"added": added, "updated": updated, "unchanged": unchanged, "ids": ids}

    def _drop_chunks(self, db, doc_id):
        if self.fts:
            db.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE doc_id=?)", (doc_id,))
        db.execute("DELETE FROM vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE doc_id=?)", (doc_id,))
        db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))

    def delete_document(self, doc_id):
        with self.tx() as db:
            self._drop_chunks(db, doc_id)
            n = db.execute("DELETE FROM documents WHERE id=?", (doc_id,)).rowcount
        self.vector_version += 1
        return n

    def doc_row(self, row, body=True):
        d = {"id": row["id"], "collection_id": row["collection_id"], "ext_id": row["ext_id"], "title": row["title"],
             "url": row["url"], "source": row["source"], "date": row["doc_date"], "meta": _uj(row["meta"]),
             "created": row["created"], "updated": row["updated"]}
        if body:
            d["body"] = row["body"]
        else:
            d["body_chars"] = len(row["body"] or "")
        return d

    def get_document(self, doc_id, with_chunks=False):
        row = self.one("SELECT * FROM documents WHERE id=?", (int(doc_id),))
        if not row:
            raise StoreError("document not found")
        d = self.doc_row(row)
        if with_chunks:
            d["chunks"] = [dict(r) for r in self.q("SELECT id, ord, section, text FROM chunks WHERE doc_id=? ORDER BY ord", (d["id"],))]
        return d

    def list_documents(self, cid, offset=0, limit=50, q=""):
        c = self.get_collection(cid)
        limit = max(1, min(int(limit), 500))
        if q:
            rows = self.q("SELECT * FROM documents WHERE collection_id=? AND (title LIKE ? OR ext_id LIKE ?) ORDER BY updated DESC LIMIT ? OFFSET ?",
                          (c["id"], "%" + q + "%", "%" + q + "%", limit, int(offset)))
        else:
            rows = self.q("SELECT * FROM documents WHERE collection_id=? ORDER BY updated DESC LIMIT ? OFFSET ?",
                          (c["id"], limit, int(offset)))
        return {"total": c["documents"], "items": [self.doc_row(r, body=False) for r in rows]}

    def iter_documents(self, cid, batch=200):
        c = self.get_collection(cid)
        last = 0
        while True:
            rows = self.q("SELECT * FROM documents WHERE collection_id=? AND id>? ORDER BY id LIMIT ?", (c["id"], last, batch))
            if not rows:
                return
            for r in rows:
                last = r["id"]
                yield self.doc_row(r)

    # search -------------------------------------------------------------
    def fts_search(self, query, collection_ids=None, limit=50):
        """BM25 over chunks. Returns [(chunk_id, score)] best first (score: higher is better)."""
        coll_sql, args = "", []
        if collection_ids:
            coll_sql = " AND c.collection_id IN (%s)" % ",".join("?" * len(collection_ids))
            args = list(collection_ids)
        if self.fts:
            expr = textproc.parse_query(query)
            if not expr:
                return []
            sql = ("SELECT c.id, bm25(chunks_fts, 2.0, 1.0) AS s FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
                   "WHERE chunks_fts MATCH ?" + coll_sql + " ORDER BY s LIMIT ?")
            try:
                rows = self.q(sql, [expr] + args + [int(limit)])
            except sqlite3.OperationalError as error:
                raise StoreError("query syntax: %s" % error)
            return [(r[0], -r[1]) for r in rows]
        terms = textproc.query_terms(query)
        if not terms:
            return []
        like = " AND ".join("c.text LIKE ?" for _ in terms)
        rows = self.q("SELECT c.id FROM chunks c WHERE " + like + coll_sql + " LIMIT ?",
                      ["%" + t + "%" for t in terms] + args + [int(limit)])
        return [(r[0], 1.0) for r in rows]

    def chunks_with_docs(self, chunk_ids):
        if not chunk_ids:
            return {}
        rows = self.q("SELECT c.id AS cid, c.section, c.text, c.ord, d.id AS did, d.title, d.url, d.ext_id, d.doc_date, d.meta, "
                      "d.source, d.collection_id, k.name AS collection FROM chunks c JOIN documents d ON d.id=c.doc_id "
                      "JOIN collections k ON k.id=c.collection_id WHERE c.id IN (%s)" % ",".join("?" * len(chunk_ids)),
                      list(chunk_ids))
        return {r["cid"]: r for r in rows}

    # vectors ------------------------------------------------------------
    def put_vectors(self, items, model):
        """items: [(chunk_id, [floats])]."""
        n = 0
        with self.tx() as db:
            for chunk_id, vec in items:
                row = db.execute("SELECT collection_id FROM chunks WHERE id=?", (int(chunk_id),)).fetchone()
                if not row:
                    continue
                blob = array("f", [float(x) for x in vec]).tobytes()
                db.execute("INSERT OR REPLACE INTO vectors(chunk_id,collection_id,model,dim,vec) VALUES(?,?,?,?,?)",
                           (int(chunk_id), row[0], model, len(vec), blob))
                n += 1
        if n:
            self.vector_version += 1
        return n

    def chunks_missing_vectors(self, cid, limit=64):
        return self.q("SELECT c.id, c.section, c.text, d.title FROM chunks c JOIN documents d ON d.id=c.doc_id "
                      "LEFT JOIN vectors v ON v.chunk_id=c.id WHERE c.collection_id=? AND v.chunk_id IS NULL ORDER BY c.id LIMIT ?",
                      (int(cid), int(limit)))

    def load_vectors(self, collection_ids=None):
        sql, args = "SELECT chunk_id, collection_id, model, dim, vec FROM vectors", []
        if collection_ids:
            sql += " WHERE collection_id IN (%s)" % ",".join("?" * len(collection_ids))
            args = list(collection_ids)
        return self.q(sql, args)

    # stats --------------------------------------------------------------
    def stats(self):
        out = {"fts5": self.fts, "sqlite": sqlite3.sqlite_version}
        for t in ("collections", "documents", "chunks", "vectors", "patents", "devices", "passkeys", "chat_messages"):
            out[t] = self.one("SELECT COUNT(*) FROM %s" % t)[0]
        page = self.one("PRAGMA page_count")[0] * self.one("PRAGMA page_size")[0]
        out["db_bytes"] = page
        return out

    # generic json-row helpers used by patents/chat ----------------------
    @staticmethod
    def dumps(v):
        return _j(v)

    @staticmethod
    def loads(v):
        return _uj(v)
