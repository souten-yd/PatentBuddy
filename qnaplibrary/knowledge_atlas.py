"""K6c global Knowledge Atlas: bounded read-only catalog projection.

Not a technical-causality engine. Collection membership is just provenance,
never an inferred patent/technology relation. Graph stays within the existing
ResearchDataHub SQLite authority; does not materialize a second graph or
read the private original body for global navigation.
"""
from .store import StoreError

MAX_COLLECTIONS = 10
MAX_SAMPLE = 5
MAX_NODES = 1 + MAX_COLLECTIONS * (MAX_SAMPLE + 1)
MAX_EDGES = MAX_COLLECTIONS * (MAX_SAMPLE + 1)


def _limit(value, low, high, field):
    if type(value) is not int or value < low or value > high:
        raise StoreError('invalid atlas %s' % field)
    return value


def read(store, *, cursor=0, limit=MAX_COLLECTIONS):
    """One bounded keyset page of collections and up to 5 recent documents each.

    Uses the existing collections PK and documents_coll_id index. It never
    fetches PDF bytes, original document bodies, raw analysis JSON or patents.
    The collection membership edge means storage only; not AI similarity.
    """
    _limit(cursor, 0, 2**63 - 1, 'cursor')
    _limit(limit, 1, MAX_COLLECTIONS, 'limit')
    with store.lock:
        collections = store.db.execute(
            'SELECT id,name,kind FROM collections WHERE id>? '
            'ORDER BY id LIMIT ?',
            (cursor, limit + 1),
        ).fetchall()
        has_more = len(collections) > limit
        nodes = [{
            'id': 'atlas:root', 'kind': 'overview', 'label': 'ResearchDataHub',
            'status': 'catalog_index', 'basis': 'catalog_index',
        }]
        edges = []
        for item in collections[:limit]:
            collection_id = item['id']
            # Avoid an exact COUNT(*) that would traverse millions of
            # collection entries on a low-power QNAP just to draw a graph.
            bounded_count = store.db.execute(
                'SELECT COUNT(*) FROM (SELECT id FROM documents '
                'WHERE collection_id=? ORDER BY id DESC LIMIT 1001)',
                (collection_id,),
            ).fetchone()[0]
            cid = 'c:%d' % collection_id
            nodes.append({
                'id': cid, 'kind': 'collection', 'label': item['name'],
                'collection_id': collection_id, 'collection_kind': item['kind'],
                'document_count': min(bounded_count, 1000),
                'count_is_lower_bound': bounded_count > 1000,
                'status': 'catalog_index',
                'basis': 'catalog_index',
            })
            edges.append({
                'id': 'catalog:%d' % collection_id,
                'source': 'atlas:root', 'target': cid,
                'basis': 'catalog_index', 'relation': 'collection',
            })
            # A sample only, never imply the collection has just these docs.
            rows = store.db.execute(
                'SELECT id,title FROM documents WHERE collection_id=? '
                'ORDER BY id DESC LIMIT ?',
                (collection_id, MAX_SAMPLE),
            ).fetchall()
            for row in rows:
                nid = 'd:%d' % row['id']
                nodes.append({
                    'id': nid, 'kind': 'document',
                    'label': row['title'] or '文献 %d' % row['id'],
                    'document_id': row['id'], 'collection_id': collection_id,
                    'status': 'catalog_sample', 'basis': 'catalog_index',
                })
                edges.append({
                    'id': 'member:%d:%d' % (collection_id, row['id']),
                    'source': cid, 'target': nid,
                    'basis': 'catalog_index', 'relation': 'collection_membership',
                })
        return {
            'root': 'atlas:root', 'nodes': nodes, 'edges': edges,
            'next_cursor': collections[limit - 1]['id'] if has_more else None,
            'truncated': has_more or any(x['document_count'] > MAX_SAMPLE for x in nodes if x['kind'] == 'collection'),
            'max_collections': MAX_COLLECTIONS, 'sample_per_collection': MAX_SAMPLE,
            'scope': 'catalog_sample', 'read_only': True,
            'disclaimer': (
                'Storage collection membership only. This atlas does not infer '
                'similarity, causality or patent relationships. Open an individual '
                'document for approved evidence links and AI-reviewed concepts.'
            ),
        }
