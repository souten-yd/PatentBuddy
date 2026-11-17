"""K3: bounded read-only source map against real SQLite and HTTP routes."""
import datetime
import json
import unittest

from qnaplibrary import evidence_graph
from qnaplibrary.knowledge_generation import _from_model, serialize
from tests.helpers import Client, LiveServer

PROOF = {
    'execution_policy': 'local_only',
    'revision_kind': 'host_process_file_metadata_v1',
    'model_ref': 'a' * 64, 'runtime_ref': 'b' * 64,
}
BODY = '温度上昇で高速に加速し、低温側は緩やかに減速する。' + ' '.join(
    '引用%02d' % i for i in range(12))
QUOTE = '低温側は緩やかに減速する。'


class KnowledgeMapTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveServer()
        self.addCleanup(self.live.close)
        self.admin = Client(self.live.base)
        self.admin.login_setup()
        self.store = self.live.app.store
        self.assertEqual(self.admin.call('POST', '/api/v1/collections',
                                         {'name': 'map-tests'})[0], 200)
        self.assertEqual(self.admin.call('POST', '/api/v1/collections/map-tests/documents', {
            'documents': [{'id': 'a', 'title': '温度制御文献A', 'body': BODY},
                          {'id': 'b', 'title': '制御文献B', 'body': '文献Bは文献Cを引用する。'},
                          {'id': 'c', 'title': '制御文献C', 'body': '資料Cの技術構成。'}]})[0], 200)
        docs = self.store.list_documents('map-tests')['items']
        self.ids = {d['ext_id']: d['id'] for d in docs}
        self.a, self.b, self.c = [self.ids[x] for x in ('a', 'b', 'c')]
        self.doc = self.store.get_document(self.a)
        self.path = '/api/v1/documents/%d/knowledge-map' % self.a
        self.store_path = '/api/v1/documents/%d/knowledge-proposals' % self.a

    def add_essence(self, name='map-1', *, items=None):
        if items is None:
            items = [{
                'kind': 'principle', 'statement': '高温方向を優先する制御原理',
                'evidence': {'quote': QUOTE},
                'conditions': ['温度センサがある'],
                'limitations': ['制御安定性の追加検証が必要'],
            }]
        proposal = _from_model(self.doc, PROOF, json.dumps({'items': items},
                                                           ensure_ascii=False))
        status, response = self.admin.call('POST', self.store_path, {
            'id': name, 'kind': 'knowledge',
            'source_revision': self.doc['revision'],
            'content': serialize(proposal),
        })
        self.assertEqual(status, 200, response)
        return name

    def approve(self, proposal, index=0, request_id='0' * 32):
        path = self.store_path + '/' + proposal + '/reviews'
        value = {'request_id': request_id, 'source_revision': self.doc['revision'],
                 'item_index': index, 'decision': 'approved'}
        status, result = self.admin.call('POST', path, value)
        self.assertEqual(status, 200, result)

    def add_graph_relation(self, src, dest, identifier, *, basis='factual'):
        source = self.store.get_document(src)
        text = source['body']
        quote = '温度上昇' if src == self.a else '文献B'
        start = text.index(quote)
        target = self.store.get_document(dest)
        relation = 'citation' if basis == 'factual' else 'solution'
        data = {
            'id': identifier,
            'source': {'kind': 'document', 'key': str(src),
                       'label': source['title']},
            'target': {'kind': 'document', 'key': str(dest),
                       'label': target['title']},
            'relation': relation,
            'basis': basis,
            'confidence': 1.0,
            'model': '' if basis == 'factual' else 'local-synthetic-test',
            'evidence': {
                'doc_id': src, 'revision': source['revision'],
                'start': start, 'end': start + len(quote), 'quote': quote,
                'retrieved_at': datetime.datetime.now(
                    datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'method': 'explicit_test',
            },
        }
        saved = evidence_graph.save(self.store, data, 'admin')
        evidence_graph.review(self.store, identifier, 'approved', 'admin')
        return saved

    def get(self, query=''):
        code, result = self.admin.call('GET', self.path + query)
        self.assertEqual(code, 200, result)
        return result

    def test_only_approved_current_essence_is_in_default_map(self):
        name = self.add_essence()
        before = self.get()
        self.assertEqual([n['id'] for n in before['nodes']], ['d:%d' % self.a])
        opt = self.get('?include_unreviewed=true')
        item = next(n for n in opt['nodes'] if n['id'] == 'k:map-1:0')
        self.assertEqual(item['review_status'], 'unreviewed')
        self.approve(name)
        result = self.get()
        essence = next(n for n in result['nodes'] if n['id'] == 'k:map-1:0')
        self.assertEqual(essence['basis'], 'model_inference')
        self.assertEqual(essence['review_status'], 'approved')
        self.assertEqual(essence['evidence']['quote'], QUOTE)
        edge = next(e for e in result['edges'] if e['target'] == essence['id'])
        self.assertEqual((edge['relation'], edge['basis']),
                         ('proposal_evidence_source', 'provenance_only'))
        self.assertIn('not a verified patent fact', result['disclaimer'])

    def test_factual_graph_relation_and_two_hop_traversal(self):
        self.add_graph_relation(self.a, self.b, 'factual-1')
        self.add_graph_relation(self.b, self.c, 'factual-2')
        one = self.get()
        ids = {n['id'] for n in one['nodes']}
        self.assertIn('d:%d' % self.b, ids)
        self.assertNotIn('d:%d' % self.c, ids)
        two = self.get('?hops=2')
        self.assertIn('d:%d' % self.c, {n['id'] for n in two['nodes']})
        self.assertEqual(sum(e['basis'] == 'factual' for e in two['edges']), 2)
        self.assertTrue(all(e['review_status'] == 'approved'
                            for e in two['edges'] if e['basis'] == 'factual'))

    def test_reviewed_inference_graph_edges_never_become_factual(self):
        self.add_graph_relation(self.a, self.b, 'inferred-1', basis='inferred')
        default = self.get()
        self.assertEqual(default['edges'], [])
        optin = self.get('?include_unreviewed=true')
        self.assertEqual(optin['edges'], [])
        self.assertNotIn('d:%d' % self.b, {n['id'] for n in optin['nodes']})

    def test_change_invalidates_graph_and_essence_but_preserves_history(self):
        name = self.add_essence()
        self.approve(name)
        self.add_graph_relation(self.a, self.b, 'factual-before-edit')
        self.assertEqual(len(self.get()['edges']), 2)
        self.assertEqual(self.admin.call('POST', '/api/v1/collections/map-tests/documents', {
            'documents': [{'id': 'a', 'title': '温度制御文献A', 'body': '改訂済の本文'}]})[0], 200)
        current = self.get()
        self.assertEqual(current['edges'], [])
        self.assertEqual(len(current['nodes']), 1)
        historical = self.get('?include_unreviewed=true')
        stale = next(n for n in historical['nodes'] if n['id'] == 'k:map-1:0')
        self.assertTrue(stale['stale'])
        self.assertEqual(stale['review_status'], 'unreviewed')
        self.assertEqual(stale['previous_decision'], 'approved')
        self.assertEqual(self.store.one(
            "SELECT review_status FROM graph_edges WHERE id='factual-before-edit'")[0],
            'unreviewed')

    def test_read_is_bounded_and_never_writes(self):
        self.add_graph_relation(self.a, self.b, 'factual-1')
        self.add_essence()
        self.approve('map-1')
        initial = self.store.db.total_changes
        for _ in range(3):
            result = self.get('?hops=2')
            self.assertLessEqual(len(result['nodes']), 36)
            self.assertLessEqual(len(result['edges']), 52)
            self.assertEqual(result['limits'], {'nodes': 36, 'edges': 52})
        self.assertEqual(self.store.db.total_changes, initial)

    def test_dense_candidates_are_truncated_not_all_rendered(self):
        items = [{
            'kind': 'principle', 'statement': '明示引用%02dの抽出' % n,
            'evidence': {'quote': '引用%02d' % n},
            'conditions': [], 'limitations': [],
        } for n in range(12)]
        for i in range(5):
            self.add_essence(name='dense-%d' % i, items=items)
        result = self.get('?include_unreviewed=true')
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['nodes']), 36)
        self.assertLessEqual(len(result['edges']), 52)
        self.assertEqual(len(result['nodes']), 36)

    def test_scope_and_bad_parameters(self):
        anonymous = Client(self.live.base)
        self.assertEqual(anonymous.call('GET', self.path)[0], 401)
        for scope in ('published', 'knowledge_propose', 'knowledge_review'):
            status, dev = self.admin.call('POST', '/api/devices',
                                          {'name': 'map-' + scope, 'scopes': scope})
            self.assertEqual(status, 200)
            client = Client(self.live.base)
            client.token = dev['token']
            self.assertEqual(client.call('GET', self.path)[0], 403)
        for query in ('?hops=0', '?hops=3', '?hops=true',
                      '?include_unreviewed=maybe'):
            self.assertEqual(self.admin.call('GET', self.path + query)[0], 400)
        self.assertEqual(self.admin.call('POST', self.path, {})[0], 404)


if __name__ == '__main__':
    unittest.main()
