"""K3b: explicit, scoped hypothesis links sourced from K2 human-reviewed knowledge.

Both actions run on ResearchDataHub's existing SQLite, with no model calls.
Registration is never an approval; approval never changes basis='inferred'.
"""
import datetime
import hashlib
import json
import re

from . import evidence_graph
from .knowledge_essence import KnowledgeProposalError, validate
from .knowledge_reviews import document_epoch
from .knowledge_store import KnowledgeConflictError
from .store import StoreError

ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
REV = re.compile(r'[a-f0-9]{64}\Z')
GRAPH_REV = re.compile(r'[a-f0-9]{32}\Z')
RELATIONS = frozenset(evidence_graph.INFERRED)


def _identifier(value, name='link'):
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise StoreError('invalid ' + name + ' identifier')
    return value


def _document(store, db, doc_id):
    if type(doc_id) is not int or not 1 <= doc_id <= 2**63 - 1:
        raise StoreError('invalid document')
    row = db.execute(
        'SELECT id,title,body,hash,source FROM documents WHERE id=?', (doc_id,)
    ).fetchone()
    if row is None:
        raise StoreError('knowledge link document not found')
    return row, store.document_revision(row)


def _reviewed_source(store, db, doc_id, proposal_id, item_index, source_revision=None):
    _identifier(proposal_id, 'proposal')
    if type(item_index) is not int or not 0 <= item_index < 12:
        raise StoreError('invalid knowledge item')
    document, revision = _document(store, db, doc_id)
    if source_revision is not None and revision != source_revision:
        raise KnowledgeConflictError('source document changed; reload evidence')
    analysis = db.execute(
        "SELECT id,doc_id,source_revision,content,created FROM document_analyses "
        "WHERE id=? AND kind='knowledge'", (proposal_id,)
    ).fetchone()
    if analysis is None or analysis['doc_id'] != doc_id:
        raise StoreError('knowledge source proposal not found')
    if analysis['source_revision'] != revision:
        raise KnowledgeConflictError('knowledge proposal source is outdated')
    try:
        parsed = validate(
            {'id': doc_id, 'revision': revision, 'body': document['body']},
            json.loads(analysis['content']),
        )
    except (ValueError, TypeError, KeyError, KnowledgeProposalError):
        raise StoreError('knowledge evidence is invalid') from None
    if item_index >= len(parsed['items']):
        raise StoreError('knowledge item not found')
    epoch = document_epoch(db, doc_id)
    review = db.execute(
        'SELECT decision,source_revision,source_epoch FROM knowledge_reviews '
        'WHERE proposal_id=? AND item_index=? ORDER BY seq DESC LIMIT 1',
        (proposal_id, item_index),
    ).fetchone()
    if (review is None or review['decision'] != 'approved'
            or review['source_revision'] != revision or review['source_epoch'] != epoch):
        raise KnowledgeConflictError('knowledge item requires a current human approval')
    return document, revision, epoch, parsed, parsed['items'][item_index], analysis


def register(store, doc_id, proposal_id, value, actor):
    """Register a hypothesis as UNREVIEWED in the PR23 graph (explicit action)."""
    if not isinstance(actor, str) or not re.fullmatch(r'(admin|device:[0-9]+)', actor):
        raise StoreError('authenticated link editor is required')
    if not isinstance(value, dict) or set(value) != {
        'item_index', 'source_revision', 'target_doc_id',
        'target_revision', 'relation', 'confirm_evidence',
    }:
        raise StoreError('invalid knowledge link registration fields')
    index, relation, target_id = value['item_index'], value['relation'], value['target_doc_id']
    src_revision, dst_revision = value['source_revision'], value['target_revision']
    if (not isinstance(src_revision, str) or REV.fullmatch(src_revision) is None
            or not isinstance(dst_revision, str) or REV.fullmatch(dst_revision) is None
            or not isinstance(relation, str) or relation not in RELATIONS
            or value['confirm_evidence'] is not True
            or type(target_id) is not int):
        raise StoreError('explicit evidence and inferred relation required')
    with store.tx() as db:
        src, rev, epoch, parsed, item, analysis = _reviewed_source(
            store, db, doc_id, proposal_id, index, src_revision,
        )
        if target_id == doc_id:
            raise StoreError('select a different document as the relation target')
        target, actual_target_revision = _document(store, db, target_id)
        if dst_revision != actual_target_revision:
            raise KnowledgeConflictError('target document changed; select it again')
        # A stable deterministic ID makes retry cheap without re-writing an edge.
        unique = json.dumps(
            [proposal_id, index, doc_id, rev, epoch, target_id, dst_revision, relation],
            ensure_ascii=False, separators=(',', ':'),
        )
        edge_id = 'klink_' + hashlib.sha256(unique.encode('utf-8')).hexdigest()
        if len(edge_id) > 128:
            raise StoreError('invalid link identifier')
        proof = parsed['generation']
        # Reuse PR23's immutable node-key/label if the document has already
        # appeared in the graph. A title edit must not invent another graph node.
        existing_source = db.execute(
            "SELECT label FROM graph_nodes WHERE kind='document' AND node_key=?",
            (str(doc_id),)
        ).fetchone()
        existing_target = db.execute(
            "SELECT label FROM graph_nodes WHERE kind='document' AND node_key=?",
            (str(target_id),)
        ).fetchone()
        source_label = (existing_source['label'] if existing_source else
                        (src['title'] or '文献 %d' % doc_id)[:300])
        target_label = (existing_target['label'] if existing_target else
                        (target['title'] or '文献 %d' % target_id)[:300])
        # Exact quote, version, node identity and source-K2 approval are verified
        # by the same transaction as GraphRAG save and origin registration.
        evidence = item['evidence']
        result = evidence_graph.save(store, {
            'id': edge_id,
            'source': {'kind': 'document', 'key': str(doc_id), 'label': source_label},
            'target': {'kind': 'document', 'key': str(target_id), 'label': target_label},
            'relation': relation, 'basis': 'inferred',
            'model': proof['model_ref'] + ':' + proof['runtime_ref'],
            'confidence': 0.0,
            'evidence': {
                'doc_id': doc_id, 'revision': rev,
                'start': evidence['start'], 'end': evidence['end'], 'quote': evidence['quote'],
                'retrieved_at': datetime.datetime.fromtimestamp(
                    analysis['created'], datetime.timezone.utc
                ).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'method': 'human_selected_knowledge_hypothesis',
            },
        }, actor, _connection=db)
        origin = db.execute(
            'SELECT proposal_id,item_index,source_doc_id,source_epoch,target_doc_id '
            'FROM knowledge_link_origins WHERE edge_id=?', (edge_id,)
        ).fetchone()
        expected = (proposal_id, index, doc_id, epoch, target_id)
        if origin is None:
            db.execute(
                'INSERT INTO knowledge_link_origins('
                'edge_id,proposal_id,item_index,source_doc_id,source_epoch,target_doc_id) '
                'VALUES(?,?,?,?,?,?)', (edge_id,) + expected,
            )
        elif tuple(origin) != expected:
            raise KnowledgeConflictError('link identity conflicts with its origin')
        return {
            'id': result['id'], 'source_doc_id': doc_id,
            'target_doc_id': target_id, 'relation': relation,
            'basis': 'inferred', 'review_status': result['review_status'],
            'graph_revision': result['graph_revision'],
            'quote': evidence['quote'],
        }


def decide(store, identifier, value, actor):
    """Separate human decision; even approved links remain inferred."""
    _identifier(identifier)
    if not identifier.startswith('klink_'):
        raise StoreError('only explicit K3b knowledge links can be reviewed')
    if not isinstance(actor, str) or not re.fullmatch(r'(admin|device:[0-9]+)', actor):
        raise StoreError('authenticated link reviewer is required')
    if not isinstance(value, dict) or set(value) != {
        'decision', 'expected_graph_revision', 'confirm_evidence',
    }:
        raise StoreError('invalid knowledge link review fields')
    status, expected_rev = value['decision'], value['expected_graph_revision']
    if (status not in ('approved', 'rejected') or
            not isinstance(expected_rev, str) or GRAPH_REV.fullmatch(expected_rev) is None or
            value['confirm_evidence'] is not True):
        raise StoreError('explicit link review and graph version required')
    with store.tx() as db:
        row = db.execute(
            'SELECT o.proposal_id,o.item_index,o.source_doc_id,o.source_epoch,o.target_doc_id,'
            'g.stale,g.basis,g.relation,g.source_node,g.target_node,g.graph_revision '
            'FROM knowledge_link_origins o JOIN graph_edges g ON g.id=o.edge_id '
            'WHERE o.edge_id=?', (identifier,),
        ).fetchone()
        if row is None or row['stale'] or row['basis'] != 'inferred':
            raise KnowledgeConflictError('link is missing or stale')
        if row['graph_revision'] != expected_rev:
            raise KnowledgeConflictError('link review changed; refresh before confirming')
        # Source K2 human approval may have been revoked or its epoch changed.
        _reviewed_source(store, db, row['source_doc_id'],
                         row['proposal_id'], row['item_index'])
        if document_epoch(db, row['source_doc_id']) != row['source_epoch']:
            raise KnowledgeConflictError('source review epoch has changed')
        _document(store, db, row['target_doc_id'])
        for node_id, did in ((row['source_node'], row['source_doc_id']),
                             (row['target_node'], row['target_doc_id'])):
            node = db.execute('SELECT doc_id,kind FROM graph_nodes WHERE id=?',
                              (node_id,)).fetchone()
            if node is None or node['kind'] != 'document' or node['doc_id'] != did:
                raise KnowledgeConflictError('link endpoint has changed')
        result = evidence_graph.review(
            store, identifier, status, actor, expected_graph_revision=expected_rev,
            _connection=db,
        )
        return {
            'id': identifier, 'basis': 'inferred', 'review_status': result['review_status'],
            'graph_revision': result['graph_revision'],
            'source_doc_id': row['source_doc_id'],
            'target_doc_id': row['target_doc_id'],
        }


def list_for_document(store, doc_id):
    """Bounded read-only link list for a document, never GraphRAG mutation."""
    if type(doc_id) is not int or doc_id < 1 or doc_id > 2**63 - 1:
        raise StoreError('invalid knowledge link document')
    with store.lock:
        if not store.db.execute('SELECT 1 FROM documents WHERE id=?', (doc_id,)).fetchone():
            raise StoreError('knowledge link document not found')
        rows = store.db.execute(
            'SELECT o.edge_id,o.proposal_id,o.item_index,o.source_doc_id,o.source_epoch,'
            'o.target_doc_id,g.relation,g.basis,g.review_status,g.graph_revision,'
            'g.stale,g.quote,t.title AS target_title '
            'FROM knowledge_link_origins o JOIN graph_edges g ON o.edge_id=g.id '
            'JOIN documents t ON o.target_doc_id=t.id '
            'WHERE o.source_doc_id=? ORDER BY g.created DESC,g.id DESC LIMIT 30',
            (doc_id,),
        ).fetchall()
        epoch = document_epoch(store.db, doc_id)
        return {'items': [
            {
                'id': r['edge_id'], 'proposal_id': r['proposal_id'],
                'item_index': r['item_index'],
                'target_doc_id': r['target_doc_id'],
                'target_title': r['target_title'],
                'relation': r['relation'], 'basis': 'inferred',
                'review_status': r['review_status'],
                'graph_revision': r['graph_revision'],
                'stale': bool(r['stale'] or r['source_epoch'] != epoch),
                'quote': r['quote'],
            } for r in rows,
        ]}
