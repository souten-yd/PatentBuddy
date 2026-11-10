"""Explicitly published, immutable-at-approval patent excerpts on the QNAP.

A publication is a separate, manually approved snapshot. It is not a flag
on the collection, and it never exposes the original body, private metadata,
claims, notes, passwords or LLM prompts to a public-only API client.

The source hash gates visibility: any edit automatically makes that
publication inactive until an administrator reviews and approves it again.
"""
import hashlib
import hmac
import json
import secrets
import sqlite3
import time

from . import textproc


PUBLIC_SCHEMA = """
CREATE TABLE IF NOT EXISTS published_patents(
  doc_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
  public_id TEXT UNIQUE NOT NULL,
  source_hash TEXT NOT NULL,
  title TEXT NOT NULL,
  ext_id TEXT NOT NULL,
  excerpt TEXT NOT NULL,
  approved_at REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS published_source_changed AFTER UPDATE ON documents
BEGIN
  UPDATE published_patents SET source_hash='' WHERE doc_id=NEW.id AND source_hash<>'';
END;
"""
MAX_EXCERPT = 12000


class PublicCatalog:
    def __init__(self, store):
        self.store = store
        self._preview_key = secrets.token_bytes(32)
        with self.store.lock:
            self.store.db.executescript(PUBLIC_SCHEMA)
            try:
                existed = self.store.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='published_patents_fts'").fetchone()
                self.store.db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS published_patents_fts "
                    "USING fts5(title,tok,tokenize='unicode61 remove_diacritics 0')")
                self.store.db.execute(
                    "CREATE TRIGGER IF NOT EXISTS published_fts_delete AFTER DELETE ON published_patents "
                    "BEGIN DELETE FROM published_patents_fts WHERE rowid=OLD.doc_id; END")
                self.fts = True
                # A database initially created without FTS5 may later gain it.
                if not existed:
                    for r in self.store.db.execute("SELECT doc_id,title,excerpt FROM published_patents"):
                        self.store.db.execute(
                            "INSERT INTO published_patents_fts(rowid,title,tok) VALUES(?,?,?)",
                            (r["doc_id"], textproc.index_text(r["title"]),
                             textproc.index_text(r["excerpt"])))
            except sqlite3.OperationalError:
                self.fts = False

    @staticmethod
    def public_row(row):
        return {"id": row["public_id"], "title": row["title"],
                "publication_number": row["ext_id"], "text": row["excerpt"]}

    @staticmethod
    def _source(db, doc_id, excerpt):
        if isinstance(doc_id, bool) or not isinstance(doc_id, int) or not 1 <= doc_id <= 9223372036854775807:
            raise ValueError("文献IDが不正です")
        if not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > MAX_EXCERPT:
            raise ValueError("抜粋は1〜12000文字にしてください")
        source = db.execute(
            "SELECT id,title,ext_id,body,hash,updated FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        if not source:
            raise ValueError("文献が見つかりません")
        if excerpt not in source["body"]:
            raise ValueError("公開する抜粋は元文献に存在する範囲から選択してください")
        if not source["ext_id"] or len(source["ext_id"]) > 300:
            raise ValueError("公開番号は1〜300文字にしてください")
        return source

    def _signature(self, source, excerpt, expires):
        data = json.dumps([source["id"], source["hash"], source["updated"],
                           source["title"], source["ext_id"], excerpt, expires],
                          ensure_ascii=False, separators=(",", ":")).encode()
        return hmac.new(self._preview_key, data, hashlib.sha256).hexdigest()

    def preview(self, doc_id, excerpt):
        # No durable writes or network: the token binds every displayed field
        # to this source version. Restarting the server invalidates previews.
        with self.store.lock:
            source = self._source(self.store.db, doc_id, excerpt)
            expires = int(time.time()) + 600
            token = str(expires) + "." + self._signature(source, excerpt, expires)
            return {"preview_token": token, "expires_at": expires,
                    "publication": {"title": source["title"],
                                    "publication_number": source["ext_id"], "text": excerpt},
                    "external_llm_called": False}

    def approve(self, doc_id, excerpt, *, acknowledged=False, preview_token=None):
        if acknowledged is not True:
            raise ValueError("公開済み資料と送信可能な抜粋であることの明示確認が必要です")
        if not isinstance(preview_token, str) or len(preview_token) > 100:
            raise ValueError("先に送信プレビューを確認してください")
        try:
            expiry, signature = preview_token.split(".", 1)
            if not expiry.isascii() or not expiry.isdigit() or len(signature) != 64 or any(
                    c not in "0123456789abcdef" for c in signature):
                raise ValueError("invalid token")
            expires = int(expiry)
        except (ValueError, TypeError):
            raise ValueError("プレビューが不正です")
        with self.store.tx() as db:
            source = self._source(db, doc_id, excerpt)
            if expires <= time.time() or not hmac.compare_digest(
                    signature, self._signature(source, excerpt, expires)):
                raise ValueError("文献の変更または期限切れです。プレビューを再確認してください")
            key = secrets.token_urlsafe(16)
            db.execute(
                "INSERT INTO published_patents(doc_id,public_id,source_hash,title,ext_id,excerpt,approved_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(doc_id) DO UPDATE SET "
                "public_id=excluded.public_id,source_hash=excluded.source_hash,"
                "title=excluded.title,ext_id=excluded.ext_id,excerpt=excluded.excerpt,"
                "approved_at=excluded.approved_at",
                (source["id"], key, source["hash"], source["title"],
                 source["ext_id"], excerpt, time.time()))
            if self.fts:
                db.execute("DELETE FROM published_patents_fts WHERE rowid=?", (source["id"],))
                db.execute("INSERT INTO published_patents_fts(rowid,title,tok) VALUES(?,?,?)",
                           (source["id"], textproc.index_text(source["title"]),
                            textproc.index_text(excerpt)))
        return {"id": key, "approved": True}

    def revoke(self, doc_id):
        with self.store.tx() as db:
            doc_id = int(doc_id)
            if self.fts:
                db.execute("DELETE FROM published_patents_fts WHERE rowid=?", (doc_id,))
            count = db.execute("DELETE FROM published_patents WHERE doc_id=?", (doc_id,)).rowcount
        return {"revoked": bool(count)}

    def admin_list(self, limit=100):
        rows = self.store.q(
            "SELECT p.doc_id,p.public_id,p.title,p.ext_id,p.approved_at,"
            "p.source_hash=d.hash AS current_hash "
            "FROM published_patents p LEFT JOIN documents d ON d.id=p.doc_id "
            "ORDER BY p.approved_at DESC LIMIT ?", (max(1,min(int(limit),500)),))
        return {"items": [{"doc_id":r["doc_id"], "id":r["public_id"],
                           "title":r["title"], "publication_number":r["ext_id"],
                           "approved_at":r["approved_at"],"active":bool(r["current_hash"])}
                          for r in rows]}

    def get(self, public_id):
        if not isinstance(public_id, str) or len(public_id) > 80:
            return None
        r = self.store.one(
            "SELECT p.public_id,p.title,p.ext_id,p.excerpt FROM published_patents p "
            "JOIN documents d ON d.id=p.doc_id AND d.hash=p.source_hash "
            "WHERE p.public_id=?", (public_id,))
        return self.public_row(r) if r else None

    def search(self, query, limit=20):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 180:
            raise ValueError("検索語は1〜180文字にしてください")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("件数は整数で指定してください")
        limit = max(1, min(limit, 50))
        q = query.strip()
        if self.fts:
            expression = textproc.parse_query(q)
            if expression is None:
                return {"results": []}
            sql = ("SELECT p.public_id,p.title,p.ext_id,p.excerpt FROM published_patents_fts f "
                   "JOIN published_patents p ON p.doc_id=f.rowid "
                   "JOIN documents d ON d.id=p.doc_id AND d.hash=p.source_hash "
                   "WHERE published_patents_fts MATCH ? ORDER BY bm25(published_patents_fts) LIMIT ?")
            try:
                rows = self.store.q(sql, (expression, limit))
            except sqlite3.OperationalError:
                raise ValueError("公開カタログの検索式が不正です")
        else:
            # FTS5-free QNAP Python remains usable; performance is reported separately.
            term = "%" + textproc.normalize(q).replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
            rows = self.store.q(
                "SELECT p.public_id,p.title,p.ext_id,p.excerpt FROM published_patents p "
                "JOIN documents d ON d.id=p.doc_id AND d.hash=p.source_hash "
                "WHERE (lower(p.title) LIKE ? ESCAPE '\\' OR lower(p.excerpt) LIKE ? ESCAPE '\\') "
                "ORDER BY p.approved_at DESC LIMIT ?", (term,term,limit))
        return {"results": [self.public_row(r) for r in rows], "count": len(rows),
                "mode": "keyword", "external_llm_called": False}
