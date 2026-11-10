"""Immutable chart dependency tracking and explicit human reviews."""
import time
import json
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
CREATE TABLE IF NOT EXISTS analysis_graph_dependencies(
 analysis_id TEXT NOT NULL REFERENCES document_analyses(id) ON DELETE CASCADE,
 edge_id TEXT NOT NULL REFERENCES graph_edges(id) ON DELETE CASCADE,
 graph_revision TEXT NOT NULL, PRIMARY KEY(analysis_id,edge_id));
CREATE INDEX IF NOT EXISTS analysis_graph_dependencies_edge ON analysis_graph_dependencies(edge_id,analysis_id);
CREATE TRIGGER IF NOT EXISTS chart_graph_changed AFTER UPDATE OF graph_revision ON graph_edges
WHEN OLD.graph_revision!=NEW.graph_revision BEGIN
 UPDATE analysis_reviews SET stale=1,status='unreviewed' WHERE stale=0 AND analysis_id IN
 (SELECT analysis_id FROM analysis_graph_dependencies WHERE edge_id=NEW.id);
END;
CREATE TRIGGER IF NOT EXISTS chart_graph_deleted BEFORE DELETE ON graph_edges BEGIN
 UPDATE analysis_reviews SET stale=1,status='unreviewed' WHERE stale=0 AND analysis_id IN
 (SELECT analysis_id FROM analysis_graph_dependencies WHERE edge_id=OLD.id);
END;
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


GRAPH_FIELDS = ('id', 'graph_revision', 'fingerprint', 'basis', 'relation', 'model', 'confidence', 'retrieved_at', 'method')


def install(db):
    db.executescript(SCHEMA)
    db.execute('BEGIN IMMEDIATE')
    try:
        if not db.execute("SELECT 1 FROM meta WHERE key='chart_graph_dependencies_v1'").fetchone():
            cursor = db.execute("SELECT id,content FROM document_analyses WHERE kind='chart'")
            while True:
                rows = cursor.fetchmany(32)
                if not rows: break
                for row in rows:
                    try:
                        chart = json.loads(row['content'])
                        legacy = any(str(s.get('via', '')).startswith('graph:') for r in chart['rows'] for s in r['evidence'])
                    except (ValueError, KeyError, TypeError, AttributeError):
                        legacy = True
                    if legacy:
                        # Old snapshots cannot prove which approval epoch they
                        # used. Keep the immutable result, requiring regeneration.
                        db.execute("""INSERT INTO analysis_reviews(analysis_id,status,stale) VALUES(?,'unreviewed',1)
 ON CONFLICT(analysis_id) DO UPDATE SET status='unreviewed',stale=1 WHERE stale=0""", (row['id'],))
            db.execute("INSERT INTO meta(key,value) VALUES('chart_graph_dependencies_v1','1')")
        db.execute('COMMIT')
    except Exception:
        db.execute('ROLLBACK')
        raise


def validate_graph(db, chart):
    dependencies = {}
    for row in chart['rows']:
        for source in row['evidence']:
            via = source.get('via', '')
            snapshot = source.get('graph')
            if not isinstance(via, str):
                raise StoreError('invalid evidence retrieval method')
            if not via.startswith('graph:'):
                if snapshot is not None:
                    raise StoreError('graph snapshot requires graph retrieval method')
                continue
            if not isinstance(snapshot, dict) or set(snapshot) != set(GRAPH_FIELDS) or snapshot.get('id') != via[6:]:
                raise StoreError('graph evidence snapshot is required')
            edge = db.execute('SELECT * FROM graph_edges WHERE id=?', (snapshot['id'],)).fetchone()
            if (edge is None or edge['stale'] or edge['review_status'] != 'approved' or edge['basis'] != 'factual'
                    or any(snapshot[k] != edge[k] for k in GRAPH_FIELDS)
                    or source['doc_id'] != edge['evidence_doc_id'] or source['revision'] != edge['revision']
                    or source['start'] != edge['start'] or source['end'] != min(edge['end'], edge['start'] + 650)
                    or source['quote'] != edge['quote'][:650]):
                raise StoreError('graph evidence approval or version changed; regenerate chart')
            dependencies[edge['id']] = edge['graph_revision']
    return dependencies


def record(db, identifier, doc_id, revision, chart):
    graphs = validate_graph(db, chart)
    dependencies = {doc_id:revision}
    for row in chart['rows']:
        for source in row['evidence']:
            dependencies[source['doc_id']] = source['revision']
    db.execute('INSERT INTO analysis_reviews(analysis_id) VALUES(?)',(identifier,))
    db.executemany('INSERT INTO analysis_dependencies VALUES(?,?,?)',
                   [(identifier,did,rev) for did,rev in dependencies.items()])
    db.executemany('INSERT INTO analysis_graph_dependencies VALUES(?,?,?)',
                   [(identifier,eid,rev) for eid,rev in graphs.items()])


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
