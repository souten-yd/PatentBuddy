"""K2: immutable human decisions on versioned, evidence-backed knowledge items.

Review events are independent from generated content. Approval never changes
the item's model_inference basis into a fact or automatically feeds GraphRAG.
"""
import json
import re

from .knowledge_essence import KnowledgeProposalError, validate
from .knowledge_store import KnowledgeConflictError
from .store import StoreError, now


DECISIONS = frozenset(('approved', 'rejected', 'changes_requested'))
REVIEW_ID = re.compile(r'[a-f0-9]{32}\Z')
PROPOSAL_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


def submit(store, doc_id, proposal_id, value, reviewer):
    """Append one human review event; duplicate request ID causes zero writes.

    Read source, stored model proposal, and previous event in the same SQLite
    write transaction to block modification/review races. Caller authenticates
    reviewer via the dedicated knowledge_review route or admin CSRF session.
    """
    if type(doc_id) is not int or doc_id <= 0 or doc_id > 2**63 - 1:
        raise StoreError('invalid source document')
    if not isinstance(proposal_id, str) or PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise StoreError('invalid knowledge proposal ID')
    if not isinstance(reviewer, str) or not re.fullmatch(r'(admin|device:[0-9]+)', reviewer):
        raise StoreError('invalid authenticated reviewer')
    if not isinstance(value, dict) or set(value) != {
        'request_id', 'item_index', 'source_revision', 'decision',
    }:
        raise StoreError('invalid review fields')
    request_id = value['request_id']
    item_index = value['item_index']
    revision = value['source_revision']
    decision = value['decision']
    if not isinstance(request_id, str) or REVIEW_ID.fullmatch(request_id) is None:
        raise StoreError('invalid review request ID')
    if type(item_index) is not int or item_index < 0 or item_index > 11:
        raise StoreError('invalid review item index')
    if not isinstance(revision, str) or re.fullmatch(r'[a-f0-9]{64}', revision) is None:
        raise StoreError('invalid source revision')
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise StoreError('invalid review decision')
    with store.tx() as db:
        document = db.execute(
            'SELECT id,body,hash,source FROM documents WHERE id=?', (doc_id,)
        ).fetchone()
        if document is None:
            raise StoreError('knowledge document not found')
        current_revision = store.document_revision(document)
        row = db.execute(
            'SELECT doc_id,source_revision,content FROM document_analyses '
            'WHERE id=? AND kind=?', (proposal_id, 'knowledge')
        ).fetchone()
        if row is None or row['doc_id'] != doc_id:
            raise StoreError('knowledge proposal not found')
        if revision != current_revision or revision != row['source_revision']:
            raise KnowledgeConflictError('knowledge source changed; re-extract and review')
        try:
            content = json.loads(row['content'])
            validated = validate({
                'id': doc_id, 'revision': revision, 'body': document['body'],
            }, content)
        except (ValueError, TypeError, KeyError, KnowledgeProposalError):
            raise StoreError('knowledge proposal evidence is invalid') from None
        if item_index >= len(validated['items']):
            raise StoreError('review item not found')
        existing = db.execute(
            'SELECT proposal_id,item_index,decision,source_revision,reviewer '
            'FROM knowledge_reviews WHERE request_id=?', (request_id,)
        ).fetchone()
        if existing is not None:
            if tuple(existing) != (proposal_id, item_index, decision, revision, reviewer):
                raise KnowledgeConflictError('review request ID already used for another decision')
            # No UPDATE/INSERT/audit on identical retry.
        else:
            db.execute(
                'INSERT INTO knowledge_reviews('
                'request_id,proposal_id,item_index,decision,source_revision,reviewer,created) '
                'VALUES(?,?,?,?,?,?,?)',
                (request_id, proposal_id, item_index, decision, revision, reviewer, now()),
            )
            # IDs and decision only; never log patent text, claim or user notes.
            store.audit(reviewer, 'knowledge.review', '%s %d %s' %
                        (proposal_id, item_index, decision))
        return {
            'request_id': request_id, 'proposal_id': proposal_id,
            'item_index': item_index, 'status': decision, 'stale': False,
            'basis': 'model_inference',
        }


def latest(store, proposal_ids, current_revision_by_id):
    """Read newest decision per item; use one bounded query per GET page."""
    if not proposal_ids:
        return {}
    if len(proposal_ids) > 20 or any(not isinstance(p, str) or
            PROPOSAL_ID.fullmatch(p) is None for p in proposal_ids):
        raise StoreError('invalid knowledge review lookup')
    placeholders = ','.join('?' for _ in proposal_ids)
    sql = (
        'SELECT r.proposal_id,r.item_index,r.decision,r.reviewer,'
        'r.source_revision,r.created FROM knowledge_reviews r '
        'JOIN (SELECT proposal_id,item_index,MAX(seq) latest_seq FROM knowledge_reviews '
        'WHERE proposal_id IN (' + placeholders + ') '
        'GROUP BY proposal_id,item_index) current ON r.seq=current.latest_seq'
    )
    out = {pid: {} for pid in proposal_ids}
    for row in store.db.execute(sql, proposal_ids):
        pid = row['proposal_id']
        stale = row['source_revision'] != current_revision_by_id[pid]
        out[pid][str(row['item_index'])] = {
            'status': 'unreviewed' if stale else row['decision'],
            'previous_decision': row['decision'],
            'stale': stale, 'reviewed_at': row['created'],
            'reviewer': row['reviewer'],
            'basis': 'model_inference',
        }
    return out

def history(store, doc_id, proposal_id):
    """Bounded authenticated-read audit trail; source texts never leave here."""
    if type(doc_id) is not int or doc_id <= 0 or doc_id > 2**63 - 1:
        raise StoreError('invalid source document')
    if not isinstance(proposal_id, str) or PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise StoreError('invalid knowledge proposal ID')
    with store.lock:
        document = store.db.execute(
            'SELECT hash,source FROM documents WHERE id=?', (doc_id,)
        ).fetchone()
        proposal = store.db.execute(
            'SELECT doc_id,source_revision FROM document_analyses '
            'WHERE id=? AND kind=?', (proposal_id, 'knowledge')
        ).fetchone()
        if document is None or proposal is None or proposal['doc_id'] != doc_id:
            raise StoreError('knowledge proposal not found')
        current_revision = store.document_revision(document)
        rows = store.db.execute(
            'SELECT request_id,item_index,decision,source_revision,reviewer,created '
            'FROM knowledge_reviews WHERE proposal_id=? ORDER BY seq DESC LIMIT 30',
            (proposal_id,),
        ).fetchall()
        return {
            'proposal_id': proposal_id,
            'stale': proposal['source_revision'] != current_revision,
            'items': [dict(dict(row),
                           stale=row['source_revision'] != current_revision)
                      for row in rows],
        }
