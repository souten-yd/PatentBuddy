"""K4: real HTTP/SQLite validation of reviewed knowledge search and comparison."""
import json
import unittest
from unittest import mock

from qnaplibrary import knowledge_cross_search
from qnaplibrary.knowledge_generation import _from_model, serialize
from tests.helpers import Client, LiveServer

PROOF = {
    'execution_policy': 'local_only',
    'revision_kind': 'host_process_file_metadata_v1',
    'model_ref': 'a' * 64, 'runtime_ref': 'b' * 64,
}
SRC_A = '🧪温度上昇時に冷却を強め、低温時は緩やかに制御する。'
SRC_B = '低温時は緩やかに制御する一方、冷却力を優先する。'
SRC_C = '別方式の温度制御では流量を変化させる。'
COMMON = '温度検出器が正常である'


class CrossKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveServer()
        self.addCleanup(self.live.close)
        self.admin = Client(self.live.base)
        self.admin.login_setup()
        self.store = self.live.app.store
        self.assertEqual(self.admin.call('POST', '/api/v1/collections',
                                         {'name': 'cross-knowledge'})[0], 200)
        status, result = self.admin.call(
            'POST', '/api/v1/collections/cross-knowledge/documents',
            {'documents': [
                {'id': 'cross-a', 'title': '冷却制御A', 'body': SRC_A},
                {'id': 'cross-b', 'title': '冷却制御B', 'body': SRC_B},
                {'id': 'cross-c', 'title': '流量制御C', 'body': SRC_C},
            ]},
        )
        self.assertEqual(status, 200, result)
        rows = self.store.list_documents('cross-knowledge')['items']
        self.ids = {row['ext_id']: row['id'] for row in rows}
        self.docs = {key: self.store.get_document(doc_id)
                     for key, doc_id in self.ids.items()}
        self.seq = 0

    def _create(self, key, statement, quote, *, kind='principle',
                conditions=None, limitations=None, approve=True, pid=None):
        doc = self.docs[key]
        self.seq += 1
        pid = pid or 'cross-proposal-%d' % self.seq
        knowledge = _from_model(doc, PROOF, json.dumps({
            'items': [{
                'kind': kind, 'statement': statement,
                'evidence': {'quote': quote},
                'conditions': conditions if conditions is not None else [COMMON],
                'limitations': limitations if limitations is not None else ['実機確認が必要'],
            }],
        }, ensure_ascii=False))
        path = '/api/v1/documents/%d/knowledge-proposals' % doc['id']
        status, saved = self.admin.call('POST', path, {
            'id': pid, 'kind': 'knowledge', 'source_revision': doc['revision'],
            'content': serialize(knowledge),
        })
        self.assertEqual(status, 200, saved)
        if approve:
            status, decision = self.admin.call('POST', path + '/' + pid + '/reviews', {
                'request_id': '%032x' % self.seq, 'item_index': 0,
                'source_revision': doc['revision'], 'decision': 'approved',
            })
            self.assertEqual(status, 200, decision)
        return {'proposal_id': pid, 'item_index': 0, 'doc_id': doc['id']}

    def _search(self, **kwargs):
        return self.admin.call('POST', '/api/v1/knowledge/search', kwargs)

    def _compare(self, entries):
        return self.admin.call('POST', '/api/v1/knowledge/compare', {'items': [
            {'proposal_id': e['proposal_id'], 'item_index': e['item_index']}
            for e in entries
        ]})

    def test_only_current_human_approved_items_are_searchable(self):
        approved = self._create(
            'cross-a', '高温方向への迅速な応答', '温度上昇時に冷却を強め')
        self._create('cross-b', '低温側の緩慢な応答',
                     '低温時は緩やかに制御する', approve=False)
        status, result = self._search(q='高温')
        self.assertEqual(status, 200, result)
        self.assertEqual(len(result['items']), 1)
        value = result['items'][0]
        self.assertEqual(value['proposal_id'], approved['proposal_id'])
        self.assertEqual(value['basis'], 'model_inference')
        self.assertEqual(value['review_status'], 'approved')
        self.assertEqual(value['evidence']['quote'], '温度上昇時に冷却を強め')
        self.assertEqual(result['coverage'], 'paged_review_events')
        self.assertEqual(self._search(kind='effect')[1]['items'], [])
        self.assertEqual(self._search(q='温度検出器')[1]['items'][0]['doc_id'],
                         self.ids['cross-a'])

    def test_compare_two_documents_shows_literal_shared_conditions_only(self):
        first = self._create('cross-a', '冷却を強める', '温度上昇時に冷却を強め',
                             conditions=[COMMON, 'Aだけの条件'])
        second = self._create('cross-b', '低温時に緩慢な応答', '低温時は緩やかに制御する',
                              conditions=[COMMON, 'Bだけの条件'])
        status, result = self._compare([first, second])
        self.assertEqual(status, 200, result)
        self.assertEqual(result['comparison_type'], 'side_by_side_literal')
        self.assertEqual(result['shared_conditions_exact'], [COMMON])
        self.assertEqual(result['shared_limitations_exact'], ['実機確認が必要'])
        self.assertEqual(len({item['doc_id'] for item in result['items']}), 2)
        self.assertTrue(all(item['basis'] == 'model_inference' for item in result['items']))
        self.assertIn('not confirmed patent facts', result['disclaimer'])

    def test_compare_three_documents_and_distinct_document_requirement(self):
        first = self._create('cross-a', '原理A', '温度上昇時に冷却を強め')
        second = self._create('cross-b', '原理B', '低温時は緩やかに制御する')
        third = self._create('cross-c', '原理C', '流量を変化させる')
        status, comparison = self._compare([first, second, third])
        self.assertEqual(status, 200, comparison)
        self.assertEqual(len(comparison['items']), 3)
        self.assertEqual(self._compare([first, first])[0], 400)
        self.assertEqual(self._compare([first])[0], 400)
        self.assertEqual(self._compare([first, second, third, first])[0], 400)

    def test_revocation_excludes_immediately_and_comparison_fails_closed(self):
        first = self._create('cross-a', '原理A', '温度上昇時に冷却を強め')
        second = self._create('cross-b', '原理B', '低温時は緩やかに制御する')
        self.assertEqual(self._compare([first, second])[0], 200)
        doc = self.docs['cross-b']
        self.assertEqual(self.admin.call(
            'POST', '/api/v1/documents/%d/knowledge-proposals/%s/reviews' %
            (doc['id'], second['proposal_id']), {
                'request_id': '%032x' % 180, 'item_index': 0,
                'source_revision': doc['revision'], 'decision': 'rejected',
            })[0], 200)
        self.assertEqual(self._compare([first, second])[0], 400)
        self.assertEqual([x['doc_id'] for x in self._search(q='原理')[1]['items']],
                         [self.ids['cross-a']])

    def test_document_edit_and_revert_never_reactivate_approved_search_hit(self):
        first = self._create('cross-a', '高温応答の原理', '温度上昇時に冷却を強め')
        self.assertEqual(len(self._search(q='高温')[1]['items']), 1)
        for body in ('更新された原文', SRC_A):
            self.assertEqual(self.admin.call(
                'POST', '/api/v1/collections/cross-knowledge/documents',
                {'documents': [{
                    'id': 'cross-a', 'title': '冷却制御A', 'body': body,
                }]})[0], 200)
        self.assertEqual(self._search(q='高温')[1]['items'], [])
        second = self._create('cross-b', '低温応答の原理', '低温時は緩やかに制御する')
        self.assertEqual(self._compare([first, second])[0], 400)

    def test_no_writes_for_search_or_compare_and_untrusted_queries_rejected(self):
        one = self._create('cross-a', '温度制御A', '温度上昇時に冷却を強め')
        two = self._create('cross-b', '温度制御B', '低温時は緩やかに制御する')
        changes = self.store.db.total_changes
        for _ in range(3):
            self.assertEqual(self._search(q='温度')[0], 200)
            self.assertEqual(self._compare([one, two])[0], 200)
        self.assertEqual(self.store.db.total_changes, changes)
        for invalid in ({'q': 'a' * 121}, {'q': '\n'}, {'kind': 'illegal'},
                        {'limit': True}, {'limit': 21}, {'cursor': True},
                        {'cursor': -1}, {'cursor': '0 OR 1=1'}, {'extra': 'unexpected'}):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.admin.call('POST', '/api/v1/knowledge/search',
                                                 invalid)[0], 400)
        self.assertEqual(self.admin.call('POST', '/api/v1/knowledge/compare',
                                         {'items': 'not-a-list'})[0], 400)

    def test_result_limit_and_scan_truncated_are_explicit(self):
        self._create('cross-a', '測定基準A', '温度上昇時に冷却を強め')
        self._create('cross-b', '測定基準B', '低温時は緩やかに制御する')
        self._create('cross-c', '測定基準C', '流量を変化させる')
        status, one = self._search(q='測定基準', limit=1)
        self.assertEqual(status, 200, one)
        self.assertEqual(len(one['items']), 1)
        self.assertTrue(one['truncated'])
        with mock.patch.object(knowledge_cross_search, 'MAX_SCAN', 2):
            status, limited = self._search(q='測定基準')
        self.assertEqual(status, 200, limited)
        self.assertEqual(limited['scan_limit'], 2)
        self.assertEqual(limited['scanned'], 2)
        self.assertTrue(limited['truncated'])
        self.assertIsInstance(limited['next_cursor'], int)
        with mock.patch.object(knowledge_cross_search, 'MAX_SCAN', 2):
            status, following = self._search(q='測定基準', cursor=limited['next_cursor'])
        self.assertEqual(status, 200, following)
        self.assertEqual(len(following['items']), 1)
        first_ids = {(x['proposal_id'], x['item_index']) for x in limited['items']}
        self.assertNotIn((following['items'][0]['proposal_id'],
                          following['items'][0]['item_index']), first_ids)
        self.assertIsNone(following['next_cursor'])

    def test_pages_continue_past_rejected_events_without_resurrecting_prior_approvals(self):
        a = self._create('cross-a', '原理A', '温度上昇時に冷却を強め')
        b = self._create('cross-b', '原理B', '低温時は緩やかに制御する')
        c = self._create('cross-c', '原理C', '流量を変化させる')
        for n, source in enumerate((a, b), start=201):
            doc = self.docs['cross-a' if source is a else 'cross-b']
            status, value = self.admin.call(
                'POST', '/api/v1/documents/%d/knowledge-proposals/%s/reviews' %
                (doc['id'], source['proposal_id']),
                {'request_id': '%032x' % n, 'item_index': 0,
                 'source_revision': doc['revision'], 'decision': 'rejected'},
            )
            self.assertEqual(status, 200, value)
        with mock.patch.object(knowledge_cross_search, 'MAX_SCAN', 2):
            status, first = self._search(q='原理')
            self.assertEqual(status, 200, first)
            self.assertEqual(first['items'], [])
            self.assertTrue(first['truncated'])
            self.assertIsInstance(first['next_cursor'], int)
            status, second = self._search(q='原理', cursor=first['next_cursor'])
            self.assertEqual(status, 200, second)
            self.assertEqual([x['proposal_id'] for x in second['items']],
                             [c['proposal_id']])
            self.assertNotIn(a['proposal_id'],
                             [x['proposal_id'] for x in second['items']])
            self.assertNotIn(b['proposal_id'],
                             [x['proposal_id'] for x in second['items']])

    def test_read_only_scopes_do_not_open_private_data_to_published_or_writers(self):
        self._create('cross-a', '温度制御A', '温度上昇時に冷却を強め')
        for scope in ('ro', 'rw', 'published', 'knowledge_propose',
                      'knowledge_review', 'knowledge_link'):
            status, data = self.admin.call('POST', '/api/devices', {
                'name': 'cross-' + scope, 'scopes': scope,
            })
            self.assertEqual(status, 200, data)
            client = Client(self.live.base)
            client.token = data['token']
            expected = 200 if scope in ('ro', 'rw') else 403
            with self.subTest(scope=scope):
                self.assertEqual(client.call('POST', '/api/v1/knowledge/search',
                                             {'q': '温度'})[0], expected)
                self.assertEqual(client.call('POST', '/api/v1/knowledge/compare',
                                             {'items': []})[0], expected)
        self.assertEqual(Client(self.live.base).call(
            'POST', '/api/v1/knowledge/search', {'q': '温度'})[0], 401)
        self.assertEqual(self.admin.call(
            'POST', '/api/v1/knowledge/search', {'q': '温度'},
            headers={'X-CSRF-Token': 'wrong'})[0], 403)


if __name__ == '__main__':
    unittest.main()
