"""K6c: real SQLite and HTTP tests for bounded Knowledge Atlas browsing."""
import unittest

from qnaplibrary import knowledge_atlas
from qnaplibrary.store import StoreError
from tests.helpers import Client, LiveServer


class KnowledgeAtlasTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveServer()
        self.addCleanup(self.live.close)
        self.admin = Client(self.live.base)
        self.admin.login_setup()
        self.store = self.live.app.store
        self.collections = [self.store.create_collection('atlas-col-%02d' % i)
                            for i in range(12)]
        with self.store.tx() as db:
            for idx, col in enumerate(self.collections):
                for doc in range((idx % 3) + 1):
                    db.execute(
                        'INSERT INTO documents(collection_id,ext_id,title,body,hash,created,updated) '
                        "VALUES(?,?,?,?,?,0,0)",
                        (col['id'], 'file-%d' % doc,
                         '元文献 %02d/%d' % (idx, doc),
                         'CONFIDENTIAL_FULL_BODY_NEVER_EXPORT' * 10, 'testhash'),
                    )

    def test_paged_overview_is_metadata_only_and_zero_write(self):
        changes = self.store.db.total_changes
        status, first = self.admin.call('GET', '/api/v1/knowledge/atlas?cursor=0&limit=10')
        self.assertEqual(status, 200, first)
        self.assertEqual(first['scope'], 'catalog_sample')
        self.assertTrue(first['read_only'])
        self.assertEqual(first['root'], 'atlas:root')
        self.assertEqual(len([n for n in first['nodes'] if n['kind'] == 'collection']), 10)
        self.assertLessEqual(len(first['nodes']), 61)
        self.assertLessEqual(len(first['edges']), 60)
        self.assertIsInstance(first['next_cursor'], int)
        self.assertNotIn('CONFIDENTIAL_FULL_BODY_NEVER_EXPORT', str(first))
        self.assertNotIn('body', str(first))
        status, second = self.admin.call('GET',
            '/api/v1/knowledge/atlas?cursor=%d&limit=10' % first['next_cursor'])
        self.assertEqual(status, 200, second)
        self.assertEqual(len([n for n in second['nodes'] if n['kind'] == 'collection']), 2)
        self.assertIsNone(second['next_cursor'])
        first_ids = {n['id'] for n in first['nodes'] if n['kind'] == 'collection'}
        second_ids = {n['id'] for n in second['nodes'] if n['kind'] == 'collection'}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(self.store.db.total_changes, changes)

    def test_drilldown_document_pages_and_no_duplicate_nodes(self):
        col = self.collections[0]['id']
        with self.store.tx() as db:
            for number in range(90):
                db.execute(
                    'INSERT INTO documents(collection_id,ext_id,title,body,hash,created,updated) '
                    "VALUES(?,?,?,?,?,0,0)",
                    (col, 'bulk-%03d' % number,
                     '高電圧インバータ文献 %03d' % number,
                     'PRIVATE_PATENT_SOURCE_NO_GRAPH_EXPORT', 'rev'),
                )
        changes = self.store.db.total_changes
        status, first = self.admin.call('GET',
            '/api/v1/knowledge/atlas?collection_id=%d&cursor=0&limit=50' % col)
        self.assertEqual(status, 200, first)
        self.assertEqual(first['scope'], 'catalog_page')
        self.assertTrue(first['read_only'])
        self.assertEqual(first['root'], 'c:%d' % col)
        self.assertEqual(len(first['nodes']), 51)
        self.assertEqual(len(first['edges']), 50)
        self.assertTrue(first['truncated'])
        self.assertNotIn('PRIVATE_PATENT_SOURCE_NO_GRAPH_EXPORT', str(first))
        status, second = self.admin.call('GET',
            '/api/v1/knowledge/atlas?collection_id=%d&cursor=%d&limit=50' %
            (col, first['next_cursor']))
        self.assertEqual(status, 200, second)
        self.assertEqual(second['scope'], 'catalog_page')
        self.assertEqual(len(second['nodes']), 42)  # 40 older + 1 original + root
        self.assertIsNone(second['next_cursor'])
        ids = [n['id'] for data in (first, second) for n in data['nodes']
               if n['kind'] == 'document']
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(self.store.db.total_changes, changes)

    def test_collection_counts_are_bounded_1001_index_entries(self):
        col = self.collections[0]['id']
        with self.store.tx() as db:
            for number in range(1005):
                db.execute(
                    'INSERT INTO documents(collection_id,ext_id,title,created,updated) '
                    'VALUES(?,?,?,0,0)',
                    (col, 'heavy-%05d' % number, 'Local-only %05d' % number),
                )
        changes = self.store.db.total_changes
        item = next(n for n in knowledge_atlas.read(self.store)['nodes']
                    if n['kind'] == 'collection' and n['collection_id'] == col)
        self.assertEqual(item['document_count'], 1000)
        self.assertTrue(item['count_is_lower_bound'])
        self.assertEqual(self.store.db.total_changes, changes)

    def test_unknown_or_invalid_pagination_rejected(self):
        invalids = (
            'cursor=1%20OR%201=1', 'limit=0', 'limit=11', 'cursor=-1',
            'cursor=9223372036854775808', 'limit=true', 'limit=1&limit=2',
            'collection_id=-1', 'collection_id=1&collection_id=1',
            'collection_id=abc', 'collection_id=9223372036854775808',
            'collection_id=1&limit=51', 'nonsense=true',
        )
        for query in invalids:
            with self.subTest(query=query):
                self.assertEqual(self.admin.call(
                    'GET', '/api/v1/knowledge/atlas?' + query)[0], 400)
        for kwargs in ({'limit': True}, {'limit': 11}, {'cursor': -1},
                       {'cursor': '10'}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(StoreError):
                    knowledge_atlas.read(self.store, **kwargs)

    def test_isolated_private_read_scopes(self):
        self.assertEqual(Client(self.live.base).call(
            'GET', '/api/v1/knowledge/atlas')[0], 401)
        for scope in ('ro', 'rw', 'published', 'knowledge_propose',
                      'knowledge_review', 'knowledge_link', 'idea_write'):
            code, token = self.admin.call('POST', '/api/devices', {
                'name': 'atlas-' + scope, 'scopes': scope,
            })
            self.assertEqual(code, 200, token)
            client = Client(self.live.base)
            client.token = token['token']
            with self.subTest(scope=scope):
                self.assertEqual(client.call('GET', '/api/v1/knowledge/atlas')[0],
                                 200 if scope in ('ro', 'rw') else 403)
        self.assertEqual(self.admin.call('GET',
            '/api/v1/knowledge/atlas?collection_id=99999999')[0], 400)

    def test_indexed_bounded_query_does_not_scan_document_body(self):
        query_plan = self.store.db.execute(
            'EXPLAIN QUERY PLAN SELECT id,title FROM documents WHERE collection_id=? '
            'AND (?=0 OR id<?) ORDER BY id DESC LIMIT ?',
            (self.collections[0]['id'], 0, 0, 51),
        ).fetchall()
        plan = ' '.join(str(part) for row in query_plan for part in row)
        self.assertIn('INDEX', plan.upper())
        self.assertNotIn('SCAN documents', plan)


if __name__ == '__main__':
    unittest.main()
