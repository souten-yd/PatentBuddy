"""Version-checked immutable knowledge proposals in ResearchDataHub's existing DB.

Only the separate, explicitly scoped knowledge API may call save(). No new
database, graph write, model execution or automatic approval is introduced.
"""
import json
import re

from .knowledge_essence import KnowledgeProposalError, validate
from .knowledge_generation import serialize
from .store import StoreError


class KnowledgeConflictError(StoreError):
    """Stale source or immutable result ID collision (HTTP 409)."""


def _payload(value):
    if not isinstance(value, dict) or set(value) != {
        'id', 'kind', 'source_revision', 'content',
    }:
        raise StoreError('invalid knowledge save fields')
    identifier = value['id']
    if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identifier):
        raise StoreError('invalid knowledge result id')
    if value['kind'] != 'knowledge':
        raise StoreError('invalid knowledge kind')
    revision = value['source_revision']
    if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{64}', revision):
        raise StoreError('invalid knowledge source revision')
    content = value['content']
    if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
        raise StoreError('invalid knowledge content')
    try:
        parsed = json.loads(content)
    except ValueError:
        raise StoreError('knowledge content must be JSON') from None
    return identifier, revision, parsed


def save(store, doc_id, value, actor='system'):
    """Validate inside the DB transaction; identical retry performs zero writes."""
    if type(doc_id) is not int or not 1 <= doc_id <= 2**63 - 1:
        raise StoreError('invalid knowledge document')
    identifier, claimed_revision, parsed = _payload(value)
    with store.tx() as db:
        doc = db.execute(
            'SELECT id,body,hash,source FROM documents WHERE id=?', (doc_id,)
        ).fetchone()
        if doc is None:
            raise StoreError('knowledge document not found')
        revision = store.document_revision(doc)
        if claimed_revision != revision:
            raise KnowledgeConflictError('knowledge source revision changed; regenerate proposals')
        try:
            validated = validate({
                'id': doc_id, 'revision': revision, 'body': doc['body'],
            }, parsed)
        except KnowledgeProposalError as error:
            raise StoreError(str(error)) from None
        canonical = serialize(validated)
        old = db.execute(
            'SELECT doc_id,kind,source_revision,content FROM document_analyses WHERE id=?',
            (identifier,),
        ).fetchone()
        if old is not None:
            if (old['doc_id'], old['kind'], old['source_revision'], old['content']) != (
                doc_id, 'knowledge', revision, canonical,
            ):
                raise KnowledgeConflictError('knowledge result id conflicts with immutable analysis')
        else:
            from .store import now
            db.execute(
                'INSERT INTO document_analyses(id,doc_id,source_revision,kind,content,created) '
                'VALUES(?,?,?,?,?,?)',
                (identifier, doc_id, revision, 'knowledge', canonical, now()),
            )
            store.audit(actor, 'knowledge.propose', '%s %s' % (doc_id, identifier))
        return {
            'id': identifier, 'doc_id': doc_id,
            'source_revision': revision, 'review_status': 'unreviewed',
        }


def list_for_document(store, doc_id):
    """Read-only, bounded snapshots; a changed document is always stale."""
    if type(doc_id) is not int or not 1 <= doc_id <= 2**63 - 1:
        raise StoreError('invalid knowledge document')
    # Keep the revision and proposals in one consistent read view.
    # Do not open a write transaction for a GET (minimal disk I/O).
    with store.lock:
        doc = store.db.execute(
            'SELECT hash,source FROM documents WHERE id=?', (doc_id,)
        ).fetchone()
        if doc is None:
            raise StoreError('knowledge document not found')
        revision = store.document_revision(doc)
        rows = store.db.execute(
            "SELECT id,doc_id,source_revision,content,created FROM document_analyses "
            "WHERE doc_id=? AND kind='knowledge' ORDER BY created DESC,id DESC LIMIT 20",
            (doc_id,),
        ).fetchall()
        from .knowledge_reviews import latest
        reviews = latest(store, [row['id'] for row in rows],
                         {row['id']: revision for row in rows})
        # Do not transform the immutable model proposal into factual content.
        return {
            'items': [dict(dict(row), stale=row['source_revision'] != revision,
                           review_status='unreviewed', reviews=reviews.get(row['id'], {}))
                      for row in rows],
        }
