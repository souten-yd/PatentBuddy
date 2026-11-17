"""K5: manual-only Idea Canvas with immutable, verifiable evidence snapshots.

No model invocation, autonomous action, publication, or external communication.
ResearchDataHub SQLite owns draft history. All writes require an explicit human
confirmation under the isolated idea_write permission or admin+CSRF.
"""
import hashlib
import json
import re
import secrets

from .knowledge_cross_search import compare
from .knowledge_reviews import document_epoch
from .knowledge_store import KnowledgeConflictError
from .store import StoreError, now

IDEA_ID = re.compile(r'idea_[a-f0-9]{32}\Z')
REQUEST_ID = re.compile(r'[a-f0-9]{32}\Z')
SOURCE_REV = re.compile(r'[a-f0-9]{64}\Z')
SELECTOR_KEYS = frozenset(('proposal_id', 'item_index', 'doc_id',
                           'source_revision', 'source_epoch', 'review_seq'))
CONTENT_LIMITS = {
    'title': 160, 'problem': 1500, 'solution': 2500,
    'effect': 1200, 'conditions': 1200, 'limitations': 1200,
}
MAX_TOTAL_CONTENT = 8000


def _id(value):
    if not isinstance(value, str) or IDEA_ID.fullmatch(value) is None:
        raise StoreError('invalid idea identifier')
    return value


def _request_id(value):
    if not isinstance(value, str) or REQUEST_ID.fullmatch(value) is None:
        raise StoreError('invalid idea request identifier')
    return value


def _actor(value):
    if not isinstance(value, str) or re.fullmatch(r'(admin|device:[0-9]+)', value) is None:
        raise StoreError('human editor authentication required')
    return value


def _content(value):
    if not isinstance(value, dict) or set(value) != set(CONTENT_LIMITS):
        raise StoreError('invalid idea draft fields')
    out = {}
    for field, maximum in CONTENT_LIMITS.items():
        text = value[field]
        if (not isinstance(text, str) or len(text) > maximum or
                any(ord(char) < 32 and char not in ('\n', '\t') for char in text)):
            raise StoreError('invalid idea draft text')
        text = text.strip()
        if field in ('title', 'problem', 'solution') and not text:
            raise StoreError('title, problem and solution must be specified by the user')
        out[field] = text
    if sum(len(x) for x in out.values()) > MAX_TOTAL_CONTENT:
        raise StoreError('idea draft is too large')
    return out


def _sources(value):
    if not isinstance(value, list) or len(value) not in (2, 3):
        raise StoreError('choose two or three reviewed knowledge sources')
    out = []
    keys = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != SELECTOR_KEYS:
            raise StoreError('invalid idea source metadata')
        pid, index, doc_id = item['proposal_id'], item['item_index'], item['doc_id']
        rev, epoch, seq = item['source_revision'], item['source_epoch'], item['review_seq']
        if (not isinstance(pid, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', pid) is None
                or type(index) is not int or not 0 <= index < 12
                or type(doc_id) is not int or not 1 <= doc_id <= 2**63 - 1
                or not isinstance(rev, str) or SOURCE_REV.fullmatch(rev) is None
                or type(epoch) is not int or not 0 <= epoch <= 2**63 - 1
                or type(seq) is not int or not 1 <= seq <= 2**63 - 1):
            raise StoreError('invalid idea source provenance')
        if (pid, index) in keys:
            raise StoreError('duplicate idea source')
        keys.add((pid, index))
        out.append({
            'proposal_id': pid, 'item_index': index, 'doc_id': doc_id,
            'source_revision': rev, 'source_epoch': epoch, 'review_seq': seq,
        })
    if len({item['doc_id'] for item in out}) < 2:
        raise StoreError('use evidence from at least two different documents')
    return out


def _current_sources(store, selected):
    """Validate sources within the caller's SQLite transaction/lock."""
    try:
        result = compare(store, {'items': [
            {'proposal_id': x['proposal_id'], 'item_index': x['item_index']}
            for x in selected
        ]})
    except StoreError:
        # Valid selectors that no longer point to currently approved evidence
        # are a conflict, not a malformed form. Fail closed and ask to recompare.
        raise KnowledgeConflictError('knowledge approval or source changed; compare again') from None
    found = result['items']
    if len(found) != len(selected):
        raise KnowledgeConflictError('knowledge comparison changed')
    for before, current in zip(selected, found):
        if any(before[key] != current[key] for key in SELECTOR_KEYS):
            raise KnowledgeConflictError('knowledge source or review changed; compare again')
    return found


def _payload(value):
    if (not isinstance(value, dict) or set(value) !=
            {'request_id', 'sources', 'content', 'confirm_manual'}):
        raise StoreError('invalid idea creation fields')
    request_id = _request_id(value['request_id'])
    if value['confirm_manual'] is not True:
        raise StoreError('explicit human confirmation required')
    return request_id, _sources(value['sources']), _content(value['content'])


def _write_hash(sources, content):
    return hashlib.sha256(json.dumps(
        {'sources': sources, 'content': content},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def create(store, value, actor):
    """Create one editable manual draft; exact request retry has zero writes."""
    actor = _actor(actor)
    request_id, selected, content = _payload(value)
    signature = _write_hash(selected, content)
    with store.tx() as db:
        prior = db.execute(
            'SELECT id,request_hash,creator FROM idea_drafts WHERE request_id=?',
            (request_id,),
        ).fetchone()
        if prior is not None:
            if prior['request_hash'] != signature or prior['creator'] != actor:
                raise KnowledgeConflictError('idea request identifier was reused')
            return {'id': prior['id'], 'version': 1, 'retry': True}
        sources = _current_sources(store, selected)
        identifier = 'idea_' + secrets.token_hex(16)
        instant = now()
        db.execute(
            'INSERT INTO idea_drafts(id,request_id,request_hash,creator,created) '
            'VALUES(?,?,?,?,?)', (identifier, request_id, signature, actor, instant),
        )
        db.execute(
            'INSERT INTO idea_versions(idea_id,version,request_id,expected_version,'
            'content,actor,created) VALUES(?,?,?,?,?,?,?)',
            (identifier, 1, request_id, 0,
             json.dumps(content, ensure_ascii=False, sort_keys=True), actor, instant),
        )
        for index, source in enumerate(sources):
            quote = source['evidence']
            db.execute(
                'INSERT INTO idea_sources(idea_id,ordinal,proposal_id,item_index,doc_id,'
                'source_revision,source_epoch,review_seq,quote,quote_start,quote_end,statement) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (identifier, index, source['proposal_id'], source['item_index'],
                 source['doc_id'], source['source_revision'], source['source_epoch'],
                 source['review_seq'], quote['quote'], quote['start'], quote['end'],
                 source['statement']),
            )
        store.audit(actor, 'idea.create', identifier)
        return {'id': identifier, 'version': 1, 'retry': False}


def _source_details(store, db, idea_id):
    rows = db.execute(
        'SELECT ordinal,proposal_id,item_index,doc_id,source_revision,source_epoch,'
        'review_seq,quote,quote_start,quote_end,statement '
        'FROM idea_sources WHERE idea_id=? ORDER BY ordinal', (idea_id,),
    ).fetchall()
    if len(rows) not in (2, 3):
        return [], True
    results = []
    any_stale = False
    for raw in rows:
        row = dict(raw)
        current = db.execute(
            'SELECT id,title,hash,source,substr(body,?,?) AS excerpt '
            'FROM documents WHERE id=?',
            (row['quote_start'] + 1,
             min(max(0, row['quote_end'] - row['quote_start']), 1201),
             row['doc_id']),
        ).fetchone()
        decision = db.execute(
            'SELECT seq,decision,source_revision,source_epoch '
            'FROM knowledge_reviews WHERE proposal_id=? AND item_index=? '
            'ORDER BY seq DESC LIMIT 1',
            (row['proposal_id'], row['item_index']),
        ).fetchone()
        proposal = db.execute(
            "SELECT doc_id,source_revision FROM document_analyses "
            "WHERE id=? AND kind='knowledge'", (row['proposal_id'],),
        ).fetchone()
        valid = (current is not None and decision is not None and proposal is not None
                 and proposal['doc_id'] == row['doc_id']
                 and proposal['source_revision'] == row['source_revision']
                 and store.document_revision(current) == row['source_revision']
                 and document_epoch(db, row['doc_id']) == row['source_epoch']
                 and decision['seq'] == row['review_seq']
                 and decision['decision'] == 'approved'
                 and decision['source_revision'] == row['source_revision']
                 and decision['source_epoch'] == row['source_epoch']
                 and row['quote_start'] >= 0
                 and 0 < row['quote_end'] - row['quote_start'] <= 1200
                 and current['excerpt'] == row['quote'])
        any_stale |= not valid
        results.append({
            'proposal_id': row['proposal_id'], 'item_index': row['item_index'],
            'doc_id': row['doc_id'], 'title': current['title'] if current else '削除済み文献',
            'source_revision': row['source_revision'],
            'source_epoch': row['source_epoch'], 'review_seq': row['review_seq'],
            'evidence': {
                'quote': row['quote'], 'start': row['quote_start'],
                'end': row['quote_end'],
            }, 'statement': row['statement'],
            'status': 'current_approved_inference' if valid else 'needs_revalidation',
            'basis': 'model_inference',
        })
    return results, any_stale


def _one(store, db, identifier, *, history=False):
    draft = db.execute(
        'SELECT id,creator,created FROM idea_drafts WHERE id=?', (identifier,)
    ).fetchone()
    if draft is None:
        raise StoreError('idea draft not found')
    current = db.execute(
        'SELECT version,content,created,actor FROM idea_versions '
        'WHERE idea_id=? ORDER BY version DESC LIMIT 1', (identifier,),
    ).fetchone()
    if current is None:
        raise StoreError('idea draft history is missing')
    sources, stale = _source_details(store, db, identifier)
    result = {
        'id': identifier, 'version': current['version'],
        'content': json.loads(current['content']),
        'created': draft['created'], 'updated': current['created'],
        'state': 'needs_revalidation' if stale else 'manual_draft',
        'stale': stale, 'sources': sources, 'basis': 'manual_hypothesis',
        'disclaimer': 'User-authored hypothesis, not an established patent fact or novelty determination',
    }
    if history:
        result['history'] = [
            {'version': row['version'], 'created': row['created']}
            for row in db.execute(
                'SELECT version,created FROM idea_versions WHERE idea_id=? '
                'ORDER BY version DESC LIMIT 20', (identifier,),
            )
        ]
    return result


def get(store, identifier):
    _id(identifier)
    with store.lock:
        return _one(store, store.db, identifier, history=True)


def get_version(store, identifier, version):
    """Inspect an immutable historical edit without changing active draft."""
    identifier = _id(identifier)
    if type(version) is not int or not 1 <= version <= 2**31 - 1:
        raise StoreError('invalid idea history version')
    with store.lock:
        current = _one(store, store.db, identifier)
        history = store.db.execute(
            'SELECT content,created FROM idea_versions '
            'WHERE idea_id=? AND version=?', (identifier, version),
        ).fetchone()
        if history is None:
            raise StoreError('idea history version not found')
        return {
            'id': identifier, 'version': version,
            'current_version': current['version'],
            'content': json.loads(history['content']),
            'created': history['created'],
            'sources': current['sources'], 'stale': current['stale'],
            'basis': 'manual_hypothesis', 'read_only': True,
        }


def list_recent(store, *, limit=20):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise StoreError('invalid idea list limit')
    with store.lock:
        rows = store.db.execute(
            'SELECT id FROM idea_drafts ORDER BY created DESC,id DESC LIMIT ?',
            (limit,),
        ).fetchall()
        return {'items': [
            {
                'id': item['id'], 'version': item['version'],
                'title': item['content']['title'], 'state': item['state'],
                'stale': item['stale'], 'updated': item['updated'],
            }
            for row in rows for item in [_one(store, store.db, row['id'])]
        ], 'limit': limit, 'truncated': len(rows) == limit}


def update(store, identifier, value, actor):
    """Append manual edit; never alter provenance or revive stale sources."""
    identifier = _id(identifier)
    actor = _actor(actor)
    if (not isinstance(value, dict) or
            set(value) != {'request_id', 'expected_version', 'content', 'confirm_manual'}):
        raise StoreError('invalid idea edit fields')
    request_id = _request_id(value['request_id'])
    expected = value['expected_version']
    if (type(expected) is not int or not 1 <= expected <= 2**31 - 2
            or value['confirm_manual'] is not True):
        raise StoreError('invalid idea edit version or confirmation')
    content = _content(value['content'])
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True)
    with store.tx() as db:
        prior = db.execute(
            'SELECT idea_id,version,expected_version,content,actor '
            'FROM idea_versions WHERE request_id=?', (request_id,),
        ).fetchone()
        if prior is not None:
            if (prior['idea_id'] != identifier or prior['expected_version'] != expected
                    or prior['content'] != canonical or prior['actor'] != actor):
                raise KnowledgeConflictError('idea edit request identifier already used')
            return {'id': identifier, 'version': prior['version'], 'retry': True}
        latest = _one(store, db, identifier)
        if latest['version'] != expected:
            raise KnowledgeConflictError('idea draft changed; reload before editing')
        if latest['stale']:
            raise KnowledgeConflictError('source review or document changed; create a new evidence-backed draft')
        if latest['content'] == content:
            # No redundant history row / WAL write for a human no-op edit.
            return {'id': identifier, 'version': latest['version'],
                    'retry': False, 'unchanged': True}
        db.execute(
            'INSERT INTO idea_versions(idea_id,version,request_id,expected_version,'
            'content,actor,created) VALUES(?,?,?,?,?,?,?)',
            (identifier, expected + 1, request_id, expected, canonical, actor, now()),
        )
        store.audit(actor, 'idea.edit', '%s v%d' % (identifier, expected + 1))
        return {'id': identifier, 'version': expected + 1, 'retry': False}
