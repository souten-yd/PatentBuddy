"""Explicitly published, immutable-at-approval patent excerpts on the QNAP.

A publication is a separate, manually approved snapshot. It is not a flag
on the collection, and it never exposes the original body, private metadata,
claims, notes, passwords or LLM prompts to a public-only API client.

The source hash gates visibility: any edit automatically makes that
publication inactive until an administrator reviews and approves it again.
"""
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
"""
MAX_EXCERPT = 12000


class PublicCatalog:
    def __init__(self, store):
        self.store = store
        with self.store.lock:
            self.store.db.executescript(PUBLIC_SCHEMA)
            try:
                self.store.db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS published_patents_fts "
                    "USING fts5(title,tok,tokenize='unicode61 remove_diacritics 0')")
                self.fts = True
                # A database initially created without FTS5 may later gain it.
                approved = self.store.db.execute("SELECT COUNT(*) FROM published_patents").fetchone()[0]
                indexed = self.store.db.execute("SELECT COUNT(*) FROM published_patents_fts").fetchone()[0]
                if approved and not indexed:
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

    def approve(self, doc_id, excerpt, *, acknowledged=False):
        if acknowledged is not True:
            raise ValueError("公開済み資料と送信可能な抜粋であることの明示確認が必要です")
        if not isinstance(excerpt, str) or not (1 <= len(excerpt.strip()) <= MAX_EXCERPT):
            raise ValueError("抜粋は1〜12000文字にしてください")
        excerpt = excerpt.strip()
        with self.store.tx() as db:
            source = db.execute(
                "SELECT id,title,ext_id,body,hash FROM documents WHERE id=?", (int(doc_id),)
            ).fetchone()
            if not source:
                raise ValueError("文献が見つかりません")
            if excerpt not in source["body"]:
                raise ValueError("公開する抜粋は元文献に存在する範囲から選択してください")
            if not source["ext_id"]:
                raise ValueError("公開番号がない文献は公開カタログへ登録できません")
            key = secrets.token_urlsafe(16)
            db.execute(
                "INSERT INTO published_patents(doc_id,public_id,source_hash,title,ext_id,excerpt,approved_at) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(doc_id) DO UPDATE SET "
                "public_id=excluded.public_id,source_hash=excluded.source_hash,"
                "title=excluded.title,ext_id=excluded.ext_id,excerpt=excluded.excerpt,"
                "approved_at=excluded.approved_at",
                (source["id"], key, source["hash"], source["title"][:500],
                 source["ext_id"][:300], excerpt, time.time()))
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
        limit = max(1, min(int(limit), 50))
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
            term = "%" + textproc.normalize(q).replace("%", r"\%").replace("_", r"\_") + "%"
            rows = self.store.q(
                "SELECT p.public_id,p.title,p.ext_id,p.excerpt FROM published_patents p "
                "JOIN documents d ON d.id=p.doc_id AND d.hash=p.source_hash "
                "WHERE (lower(p.title) LIKE ? ESCAPE '\\' OR lower(p.excerpt) LIKE ? ESCAPE '\\') "
                "ORDER BY p.approved_at DESC LIMIT ?", (term,term,limit))
        return {"results": [self.public_row(r) for r in rows], "count": len(rows),
                "mode": "keyword", "external_llm_called": False}
