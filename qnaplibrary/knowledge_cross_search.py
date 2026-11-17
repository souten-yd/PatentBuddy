"""K4: bounded, read-only search and side-by-side comparison of reviewed essences.

ResearchDataHub SQLite remains authoritative. The engine never calls a model,
uses external services, infers legal conclusions, or writes on GET/POST.
"""
import json
import re

from .knowledge_essence import KINDS, MAX_BODY, KnowledgeProposalError, validate
from .knowledge_reviews import document_epoch
from .store import StoreError

MAX_SCAN = 240
MAX_RESULTS = 20
MAX_COMPARISON = 3
MAX_SNAPSHOT_BYTES = 131072
PROPOSAL_ID = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


def _search_request(value):
    if not isinstance(value, dict) or set(value) - {'q', 'kind', 'limit', 'cursor'}:
        raise StoreError('invalid knowledge search fields')
    q = value.get('q', '')
    kind = value.get('kind', '')
    limit = value.get('limit', MAX_RESULTS)
    cursor = value.get('cursor', 0)
    if (type(cursor) is not int or not 0 <= cursor <= 2**63 - 1):
        raise StoreError('invalid knowledge search cursor')
    if (not isinstance(q, str) or len(q) > 120 or
            any(ord(c) < 32 for c in q)):
        raise StoreError('invalid search query')
    q = q.strip()
    if (not isinstance(kind, str) or kind not in KINDS | {''} or
            type(limit) is not int or not 1 <= limit <= MAX_RESULTS):
        raise StoreError('invalid knowledge search filter')
    return q, kind, limit, cursor


def _read_validated(db, row):
    """Return one K1a-valid current item; never trust review status in AI JSON."""
    if (row['source_revision'] != row['review_revision'] or
            row['source_revision'] != row['current_revision'] or
            row['source_epoch'] != row['current_epoch']):
        return None
    content = row['content']
    if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_SNAPSHOT_BYTES:
        return None
    try:
        parsed = json.loads(content)
        index = row['item_index']
        if (type(index) is not int or
                not isinstance(parsed, dict) or
                not isinstance(parsed.get('items'), list) or
                not 0 <= index < len(parsed['items'])):
            return None
        preitem = parsed['items'][index]
        if not isinstance(preitem, dict):
            return None
        document = db.execute(
            'SELECT substr(body,1,?) AS body FROM documents WHERE id=?',
            (MAX_BODY + 1, row['doc_id']),
        ).fetchone()
        if (document is None or not isinstance(document['body'], str) or
                len(document['body']) > MAX_BODY):
            return None
        checked = validate({
            'id': row['doc_id'], 'revision': row['current_revision'],
            'body': document['body'],
        }, parsed)
        return checked['items'][index]
    except (ValueError, TypeError, KeyError, KnowledgeProposalError):
        return None


def _current_row(db, raw):
    """Convert sqlite rows to a trusted, version-checked read-only projection."""
    row = dict(raw)
    if (row['source_revision'] != row['review_revision'] or
            row['source_revision'] != row['current_revision'] or
            row['source_epoch'] != row['current_epoch']):
        return None
    return row


def _project(row, item):
    return {
        'proposal_id': row['proposal_id'], 'item_index': row['item_index'],
        'doc_id': row['doc_id'], 'title': row['title'] or '無題の文献',
        'kind': item['kind'], 'statement': item['statement'],
        'conditions': item['conditions'], 'limitations': item['limitations'],
        'evidence': item['evidence'], 'source_revision': row['current_revision'],
        'reviewed_at': row['reviewed_at'],
        'review_status': 'approved', 'basis': 'model_inference',
    }


def search(store, value):
    """Search bounded batches of approved review events with keyset pagination.

    No persistent FTS/index is created. Pages are ordered by descending
    *review event sequence*. Each response scans at most MAX_SCAN events,
    and includes a cursor when more of the corpus remains. Query text stays
    in POST request bodies. Query matching uses local Python casefold.
    """
    q, kind, limit, cursor = _search_request(value)
    with store.lock:
        rows = store.db.execute(
            'SELECT r.seq,r.proposal_id,r.item_index,r.source_revision AS review_revision,'
            'r.source_epoch,r.created AS reviewed_at,a.doc_id,a.source_revision,'
            'CASE WHEN length(CAST(a.content AS BLOB))<=? '
            'THEN a.content ELSE NULL END AS content,'
            'd.title,d.hash,d.source,coalesce(ep.epoch,0) AS current_epoch '
            'FROM knowledge_reviews r '
            'JOIN document_analyses a ON a.id=r.proposal_id AND a.kind=? '
            'JOIN documents d ON d.id=a.doc_id '
            'LEFT JOIN knowledge_review_epochs ep ON ep.doc_id=d.id '
            "WHERE r.decision='approved' AND r.seq=("
            'SELECT MAX(q.seq) FROM knowledge_reviews q '
            'WHERE q.proposal_id=r.proposal_id AND q.item_index=r.item_index) '
            'AND (?=0 OR r.seq<?) '
            'ORDER BY r.seq DESC LIMIT ?',
            (MAX_SNAPSHOT_BYTES, 'knowledge', cursor, cursor, MAX_SCAN + 1),
        ).fetchall()
        truncated = len(rows) > MAX_SCAN
        items = []
        examined = 0
        last_scanned_seq = None
        for raw in rows[:MAX_SCAN]:
            # Stop before consuming the first unreturned matching item, so a
            # continuation cursor never skips anything across result pages.
            if len(items) >= limit:
                truncated = True
                break
            examined += 1
            last_scanned_seq = raw['seq']
            row = dict(raw)
            row['current_revision'] = store.document_revision(row)
            row = _current_row(store.db, row)
            if row is None:
                continue
            # Parse just enough to skip unrelated kinds/terms before fetching
            # any patent body. Revalidate against the exact source before output.
            try:
                if (not isinstance(row['content'], str) or
                        len(row['content'].encode('utf-8')) > MAX_SNAPSHOT_BYTES):
                    continue
                proposal = json.loads(row['content'])
                preitem = proposal['items'][row['item_index']]
                if not isinstance(preitem, dict):
                    continue
                if kind and preitem.get('kind') != kind:
                    continue
                text = ' '.join([
                    str(preitem.get('statement', '')),
                    *(preitem.get('conditions') if isinstance(preitem.get('conditions'), list) else []),
                    *(preitem.get('limitations') if isinstance(preitem.get('limitations'), list) else []),
                    str(preitem.get('evidence', {}).get('quote', ''))
                    if isinstance(preitem.get('evidence'), dict) else '',
                ])
                if q and q.casefold() not in text.casefold():
                    continue
            except (ValueError, TypeError, KeyError, IndexError):
                continue
            item = _read_validated(store.db, row)
            if item is None:
                continue
            items.append(_project(row, item))
        return {
            'items': items, 'truncated': truncated, 'scanned': examined,
            'next_cursor': last_scanned_seq if truncated else None,
            'scan_limit': MAX_SCAN, 'limit': limit, 'coverage': 'paged_review_events',
            'note': 'Reviewed model inferences, not established technical facts or legal conclusions',
        }


def _compare_request(value):
    if not isinstance(value, dict) or set(value) != {'items'}:
        raise StoreError('invalid knowledge comparison fields')
    selectors = value['items']
    if not isinstance(selectors, list) or not 2 <= len(selectors) <= MAX_COMPARISON:
        raise StoreError('compare 2 or 3 reviewed knowledge items')
    keys = []
    for entry in selectors:
        if (not isinstance(entry, dict) or set(entry) != {'proposal_id', 'item_index'} or
                not isinstance(entry['proposal_id'], str) or
                PROPOSAL_ID.fullmatch(entry['proposal_id']) is None or
                type(entry['item_index']) is not int or
                not 0 <= entry['item_index'] < 12):
            raise StoreError('invalid knowledge comparison selector')
        key = (entry['proposal_id'], entry['item_index'])
        if key in keys:
            raise StoreError('knowledge comparison contains duplicate items')
        keys.append(key)
    return keys


def compare(store, value):
    """Compare only exact, currently approved source statements, without AI."""
    keys = _compare_request(value)
    with store.lock:
        items = []
        for proposal_id, index in keys:
            row = store.db.execute(
                'SELECT a.id AS proposal_id,a.doc_id,'
                'CASE WHEN length(CAST(a.content AS BLOB))<=? '
                'THEN a.content ELSE NULL END AS content,a.source_revision,'
                'd.title,d.hash,d.source,r.seq,r.item_index,r.source_revision AS review_revision,'
                'r.source_epoch,r.created AS reviewed_at,'
                'coalesce(ep.epoch,0) AS current_epoch '
                'FROM document_analyses a JOIN documents d ON d.id=a.doc_id '
                'LEFT JOIN knowledge_review_epochs ep ON ep.doc_id=d.id '
                'JOIN knowledge_reviews r ON r.proposal_id=a.id AND r.item_index=? '
                "WHERE a.id=? AND a.kind='knowledge' AND r.decision='approved' "
                'AND r.seq=(SELECT MAX(q.seq) FROM knowledge_reviews q '
                'WHERE q.proposal_id=a.id AND q.item_index=?) LIMIT 1',
                (MAX_SNAPSHOT_BYTES, index, proposal_id, index),
            ).fetchone()
            if row is None:
                raise StoreError('knowledge comparison requires current human approvals')
            trusted = dict(row)
            trusted['current_revision'] = store.document_revision(trusted)
            if _current_row(store.db, trusted) is None:
                raise StoreError('knowledge comparison source is stale')
            item = _read_validated(store.db, trusted)
            if item is None:
                raise StoreError('knowledge comparison evidence is unavailable')
            items.append(_project(trusted, item))
        if len({item['doc_id'] for item in items}) < 2:
            raise StoreError('choose knowledge from at least two source documents')
        # Literal overlap only. Never invent an LLM-generated equivalence,
        # causality, novelty or legal conclusion.
        all_conditions = [set(x['conditions']) for x in items]
        all_limits = [set(x['limitations']) for x in items]
        shared_conditions = sorted(set.intersection(*all_conditions))
        shared_limitations = sorted(set.intersection(*all_limits))
        return {
            'items': items,
            'shared_conditions_exact': shared_conditions,
            'shared_limitations_exact': shared_limitations,
            'comparison_type': 'side_by_side_literal',
            'basis': 'model_inference',
            'disclaimer': (
                'Literal overlaps are not semantic equivalence. '
                'These are human-reviewed AI statements, not confirmed patent facts.'
            ),
        }
