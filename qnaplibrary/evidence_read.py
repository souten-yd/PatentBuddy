"""Bounded original-text evidence reads without transferring entire documents."""
from .store import StoreError


def identifier(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise StoreError('invalid evidence identifier')
    return value


def chunk(store, chunk_id):
    row = store.one('''SELECT c.id AS chunk_id,c.doc_id,d.hash,d.source,
 substr(c.text,1,650) AS quote,instr(d.body,substr(c.text,1,650))-1 AS start
 FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE c.id=?''', (identifier(chunk_id),))
    if row is None:
        raise StoreError('chunk not found')
    if not row['quote'] or row['start'] < 0:
        # Explicit sections may not be literal ranges of the document body.
        # Such a chunk cannot support an exact original-text citation.
        return {'chunk_id': row['chunk_id'], 'doc_id': row['doc_id'],
                'revision': store.document_revision(row), 'citable': False}
    return {'chunk_id': row['chunk_id'], 'doc_id': row['doc_id'],
            'revision': store.document_revision(row), 'citable': True,
            'start': row['start'], 'end': row['start'] + len(row['quote']), 'quote': row['quote']}


def document_range(store, doc_id, start, end, revision):
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= start + 650 or end > 2**63 - 1:
        raise StoreError('evidence range must contain 1-650 characters')
    row = store.one('''SELECT id AS doc_id,hash,source,substr(body,?,?) AS quote,
 length(body) AS body_length FROM documents WHERE id=?''', (start + 1, end - start, identifier(doc_id)))
    if row is None or store.document_revision(row) != revision or end > row['body_length']:
        raise StoreError('evidence source changed or range is invalid')
    return {'doc_id': row['doc_id'], 'revision': revision, 'start': start, 'end': end, 'quote': row['quote']}
