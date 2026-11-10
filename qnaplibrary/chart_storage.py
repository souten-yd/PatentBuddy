"""Immutable chart dependency tracking and explicit human reviews."""
import time
from .store import StoreError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS analysis_reviews(
 analysis_id TEXT PRIMARY KEY REFERENCES document_analyses(id) ON DELETE CASCADE,
 status TEXT NOT NULL DEFAULT 'unreviewed', stale INTEGER NOT NULL DEFAULT 0,
 reviewer TEXT NOT NULL DEFAULT '', reviewed_at REAL);
CREATE TABLE IF NOT EXISTS analysis_dependencies(
 analysis_id TEXT NOT NULL REFERENCES document_analyses(id) ON DELETE CASCADE,
 doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 revision TEXT NOT NULL, PRIMARY KEY(analysis_id,doc_id));
CREATE INDEX IF NOT EXISTS analysis_dependencies_doc ON analysis_dependencies(doc_id,analysis_id);
CREATE TRIGGER IF NOT EXISTS chart_source_changed AFTER UPDATE OF hash,source ON documents
WHEN OLD.hash != NEW.hash OR OLD.source != NEW.source BEGIN
 UPDATE analysis_reviews SET stale=1,status='unreviewed' WHERE stale=0 AND analysis_id IN
 (SELECT analysis_id FROM analysis_dependencies WHERE doc_id=NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS chart_source_deleted BEFORE DELETE ON documents BEGIN
 UPDATE analysis_reviews SET stale=1,status='unreviewed' WHERE stale=0 AND analysis_id IN
 (SELECT analysis_id FROM analysis_dependencies WHERE doc_id=OLD.id);
END;
'''


def record(db, identifier, doc_id, revision, chart):
    dependencies = {doc_id:revision}
    for row in chart['rows']:
        for source in row['evidence']:
            dependencies[source['doc_id']] = source['revision']
    db.execute('INSERT INTO analysis_reviews(analysis_id) VALUES(?)',(identifier,))
    db.executemany('INSERT INTO analysis_dependencies VALUES(?,?,?)',
                   [(identifier,did,rev) for did,rev in dependencies.items()])


def review(store, identifier, status, actor):
    if status not in ('approved','rejected','unreviewed'):
        raise StoreError('invalid chart review status')
    with store.tx() as db:
        row = db.execute('SELECT * FROM analysis_reviews WHERE analysis_id=?',(identifier,)).fetchone()
        if row is None or row['stale']:
            raise StoreError('chart missing or stale')
        if row['status'] != status:
            db.execute('UPDATE analysis_reviews SET status=?,reviewer=?,reviewed_at=? WHERE analysis_id=?',
                       (status,actor,time.time(),identifier))
            store.audit(actor,'chart.review',identifier+' '+status)
        return dict(db.execute('SELECT * FROM analysis_reviews WHERE analysis_id=?',(identifier,)).fetchone())
