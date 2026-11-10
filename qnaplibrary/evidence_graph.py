"""Versioned, private evidence relations; no inference or network calls here."""
import hashlib
import json
import math
import re
import time
from .store import StoreError

NODE_KINDS = ('document', 'party', 'classification', 'claim', 'concept', 'family', 'priority')
FACTUAL = ('citation', 'family', 'priority', 'applicant', 'classification', 'requirement')
INFERRED = ('problem', 'solution', 'effect', 'substitution')

SCHEMA = '''
CREATE TABLE IF NOT EXISTS graph_nodes(
 id INTEGER PRIMARY KEY, kind TEXT NOT NULL, node_key TEXT NOT NULL, label TEXT NOT NULL,
 doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE, UNIQUE(kind,node_key));
CREATE INDEX IF NOT EXISTS graph_nodes_doc ON graph_nodes(doc_id);
CREATE TABLE IF NOT EXISTS graph_edges(
 id TEXT PRIMARY KEY, source_node INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
 target_node INTEGER NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
 relation TEXT NOT NULL, basis TEXT NOT NULL, evidence_doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 revision TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, quote TEXT NOT NULL,
 retrieved_at TEXT NOT NULL, method TEXT NOT NULL, model TEXT NOT NULL, confidence REAL NOT NULL,
 fingerprint TEXT NOT NULL, review_status TEXT NOT NULL DEFAULT 'unreviewed', reviewer TEXT NOT NULL DEFAULT '',
 reviewed_at REAL, stale INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS graph_edges_source ON graph_edges(source_node,stale,review_status,id);
CREATE INDEX IF NOT EXISTS graph_edges_source_basis ON graph_edges(source_node,stale,review_status,basis,id);
CREATE INDEX IF NOT EXISTS graph_edges_target ON graph_edges(target_node,id);
CREATE INDEX IF NOT EXISTS graph_edges_evidence ON graph_edges(evidence_doc_id);
CREATE TRIGGER IF NOT EXISTS graph_evidence_changed AFTER UPDATE OF hash,source ON documents
WHEN OLD.hash != NEW.hash OR OLD.source != NEW.source BEGIN
 UPDATE graph_edges SET stale=1, review_status='unreviewed'
 WHERE stale=0 AND (evidence_doc_id=NEW.id
 OR source_node IN (SELECT id FROM graph_nodes WHERE doc_id=NEW.id)
 OR target_node IN (SELECT id FROM graph_nodes WHERE doc_id=NEW.id));
END;
'''


def _text(value, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise StoreError('invalid graph ' + name)
    return value


def _integer(value, low, high, name):
    if type(value) is not int or not low <= value <= high:
        raise StoreError('invalid graph ' + name)
    return value


def _node(db, value):
    if not isinstance(value, dict) or value.get('kind') not in NODE_KINDS:
        raise StoreError('invalid graph node')
    kind = value['kind']; key = _text(value.get('key'), 200, 'node key')
    label = _text(value.get('label'), 300, 'node label')
    doc_id = None
    if kind == 'document':
        if not re.fullmatch(r'[1-9][0-9]{0,17}', key):
            raise StoreError('invalid document node key')
        doc_id = int(key)
        if not db.execute('SELECT id FROM documents WHERE id=?', (doc_id,)).fetchone():
            raise StoreError('graph document not found')
    old = db.execute('SELECT * FROM graph_nodes WHERE kind=? AND node_key=?', (kind, key)).fetchone()
    if old:
        if old['label'] != label:
            raise StoreError('node key already has a different label')
        return old['id']
    return db.execute('INSERT INTO graph_nodes(kind,node_key,label,doc_id) VALUES(?,?,?,?)',
                      (kind, key, label, doc_id)).lastrowid


def save(store, value, actor):
    if not isinstance(value, dict):
        raise StoreError('graph edge must be an object')
    identifier = _text(value.get('id'), 128, 'id')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
        raise StoreError('invalid graph id')
    relation = value.get('relation')
    if relation not in FACTUAL + INFERRED:
        raise StoreError('invalid relation')
    basis = 'factual' if relation in FACTUAL else 'inferred'
    if value.get('basis') != basis:
        raise StoreError('relation basis mismatch')
    evidence = value.get('evidence')
    if not isinstance(evidence, dict):
        raise StoreError('evidence required')
    doc_id = _integer(evidence.get('doc_id'), 1, 2**63-1, 'evidence document')
    start = _integer(evidence.get('start'), 0, 100000000, 'start')
    end = _integer(evidence.get('end'), start+1, start+4000, 'end')
    quote = _text(evidence.get('quote'), 4000, 'quote')
    revision = _text(evidence.get('revision'), 64, 'revision')
    retrieved = _text(evidence.get('retrieved_at'), 40, 'retrieved time')
    # Explicit UTC timestamp; no inferred dates or silently replaced precision.
    import datetime
    try:
        dt = datetime.datetime.strptime(retrieved, '%Y-%m-%dT%H:%M:%SZ')
        if dt.strftime('%Y-%m-%dT%H:%M:%SZ') != retrieved:
            raise ValueError()
    except ValueError:
        raise StoreError('retrieved_at must be UTC YYYY-MM-DDTHH:MM:SSZ') from None
    method = _text(evidence.get('method'), 100, 'method')
    model = value.get('model', '')
    if not isinstance(model, str) or len(model) > 200 or (basis == 'inferred' and not model.strip()):
        raise StoreError('inferred relations require a model version')
    confidence = value.get('confidence')
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise StoreError('invalid confidence')
    if value.get('review_status', 'unreviewed') != 'unreviewed':
        raise StoreError('review requires a separate human action')
    canonical = {k: value.get(k) for k in ('id','source','target','relation','basis','evidence','model','confidence')}
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with store.tx() as db:
        doc = db.execute('SELECT body,hash,source FROM documents WHERE id=?', (doc_id,)).fetchone()
        if doc is None or store.document_revision(doc) != revision or end > len(doc['body']) or doc['body'][start:end] != quote:
            raise StoreError('evidence revision or exact quote does not match')
        old = db.execute('SELECT * FROM graph_edges WHERE id=?', (identifier,)).fetchone()
        if old:
            if old['fingerprint'] != fingerprint or old['stale']:
                raise StoreError('edge id already exists or evidence is stale; use a new version id')
            return dict(old)
        source, target = _node(db, value.get('source')), _node(db, value.get('target'))
        if source == target:
            raise StoreError('self relation is not allowed')
        db.execute('''INSERT INTO graph_edges(id,source_node,target_node,relation,basis,evidence_doc_id,
 revision,start,end,quote,retrieved_at,method,model,confidence,fingerprint,created)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (identifier, source, target, relation, basis, doc_id, revision, start, end, quote,
                    retrieved, method, model, confidence, fingerprint, time.time()))
        store.audit(actor, 'graph.add', identifier)
        return dict(db.execute('SELECT * FROM graph_edges WHERE id=?', (identifier,)).fetchone())


def review(store, identifier, status, actor):
    if status not in ('approved', 'rejected', 'unreviewed'):
        raise StoreError('invalid review status')
    with store.tx() as db:
        row = db.execute('SELECT * FROM graph_edges WHERE id=?', (identifier,)).fetchone()
        if row is None or row['stale']:
            raise StoreError('edge missing or stale; extract a new version')
        if row['review_status'] != status:
            db.execute('UPDATE graph_edges SET review_status=?,reviewer=?,reviewed_at=? WHERE id=?',
                       (status, actor, time.time(), identifier))
            store.audit(actor, 'graph.review', identifier + ' ' + status)
        return dict(db.execute('SELECT * FROM graph_edges WHERE id=?', (identifier,)).fetchone())


def expand(store, seeds, hops=1, max_nodes=50, max_edges=100, include_inferred=False):
    """Read-only outgoing expansion; unreviewed/stale edges never enter retrieval."""
    if not isinstance(seeds, list) or not 1 <= len(seeds) <= 20 or type(include_inferred) is not bool:
        raise StoreError('provide 1..20 seed node ids')
    seeds = sorted(set(_integer(x, 1, 2**63-1, 'seed') for x in seeds))
    _integer(hops, 1, 2, 'hops'); _integer(max_nodes, len(seeds), 100, 'node budget')
    _integer(max_edges, 1, 200, 'edge budget')
    nodes, edges, frontier, truncated = {}, {}, seeds, False
    # One read lock gives a coherent in-process snapshot without disk writes.
    with store.lock:
        for seed in seeds:
            row = store.db.execute('SELECT * FROM graph_nodes WHERE id=?', (seed,)).fetchone()
            if row is None:
                raise StoreError('seed node not found')
            nodes[seed] = dict(row)
        for _ in range(hops):
            following = []
            for source in frontier:
                query = "SELECT * FROM graph_edges WHERE source_node=? AND stale=0 AND review_status='approved'"
                if not include_inferred:
                    query += " AND basis='factual'"
                query += ' ORDER BY id LIMIT ?'
                remaining = max_edges - len(edges)
                rows = store.db.execute(query, (source, remaining+1)).fetchall()
                if len(rows) > remaining:
                    truncated = True
                for row in rows[:remaining]:
                    target = row['target_node']
                    if target not in nodes:
                        if len(nodes) >= max_nodes:
                            truncated = True
                            continue
                        nodes[target] = dict(store.db.execute('SELECT * FROM graph_nodes WHERE id=?', (target,)).fetchone())
                        following.append(target)
                    edges[row['id']] = dict(row)
            frontier = following
            if not frontier:
                break
    return {'nodes': list(nodes.values()), 'edges': list(edges.values()), 'truncated': truncated,
            'hops': hops, 'direction': 'outgoing', 'include_inferred': include_inferred}
