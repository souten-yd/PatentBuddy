"""K2: real HTTP/SQLite reviewer permissions and immutable decision history."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qnaplibrary.addon_client import AddonClient, AddonError
from qnaplibrary.knowledge_generation import _from_model, serialize
from tests.helpers import Client, LiveServer


PROOF = {
    'execution_policy': 'local_only',
    'revision_kind': 'host_process_file_metadata_v1',
    'model_ref': 'a' * 64, 'runtime_ref': 'b' * 64,
}
BODY = '制御を急加速し、温度が下がれば緩やかに減速する。'
ITEM = {
    'kind': 'principle', 'statement': '温度変化の方向で応答を非対称にする',
    'evidence': {'quote': '温度が下がれば緩やかに減速する。'},
    'conditions': ['温度監視'], 'limitations': ['安定性は未検証'],
}


class HumanReviewAPITests(unittest.TestCase):
    def setUp(self):
        self.live = LiveServer()
        self.addCleanup(self.live.close)
        self.admin = Client(self.live.base)
        self.admin.login_setup()
        self.store = self.live.app.store
        self.assertEqual(self.admin.call('POST', '/api/v1/collections',
                                         {'name': 'reviews'})[0], 200)
        self.assertEqual(self.admin.call('POST', '/api/v1/collections/reviews/documents',
                                         {'documents': [{'id': 'document-1', 'body': BODY}]})[0], 200)
        self.doc_id = self.store.list_documents('reviews')['items'][0]['id']
        self.doc = self.store.get_document(self.doc_id)
        proposal = _from_model(self.doc, PROOF, json.dumps({'items': [ITEM]}, ensure_ascii=False))
        self.path = '/api/v1/documents/%d/knowledge-proposals' % self.doc_id
        self.review_path = self.path + '/human-sample/reviews'
        self.assertEqual(self.admin.call('POST', self.path, {
            'id': 'human-sample', 'kind': 'knowledge',
            'source_revision': self.doc['revision'],
            'content': serialize(proposal)})[0], 200)

    def decision(self, choice='approved', request_id='a' * 32):
        return {'request_id': request_id, 'item_index': 0,
                'source_revision': self.doc['revision'], 'decision': choice}

    def token_client(self, scope):
        status, value = self.admin.call('POST', '/api/devices',
                                        {'name': 'reviewer-' + scope, 'scopes': scope})
        self.assertEqual(status, 200, value)
        c = Client(self.live.base)
        c.token = value['token']
        return c

    def state(self):
        status, value = self.admin.call('GET', self.path)
        self.assertEqual(status, 200, value)
        return value['items'][0]

    def count(self):
        return self.store.one('SELECT COUNT(*) FROM knowledge_reviews')[0]

    def test_admin_review_records_but_cannot_make_ai_inference_a_fact(self):
        status, accepted = self.admin.call('POST', self.review_path, self.decision())
        self.assertEqual(status, 200, accepted)
        self.assertEqual(accepted['basis'], 'model_inference')
        entry = self.state()
        self.assertEqual(entry['reviews']['0']['status'], 'approved')
        self.assertEqual(entry['reviews']['0']['reviewer'], 'admin')
        self.assertEqual(entry['review_status'], 'unreviewed')  # model envelope remains unchanged
        self.assertEqual(json.loads(entry['content'])['items'][0]['basis'], 'model_inference')
        self.assertEqual(json.loads(entry['content'])['items'][0]['review_status'], 'unreviewed')
        self.assertEqual(self.count(), 1)

    def test_decisions_are_append_only_and_latest_is_authoritative(self):
        decisions = [('approved', 'a'*32), ('rejected', 'b'*32),
                     ('changes_requested', 'c'*32)]
        for decision, rid in decisions:
            self.assertEqual(self.admin.call('POST', self.review_path,
                                              self.decision(decision, rid))[0], 200)
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.state()['reviews']['0']['status'], 'changes_requested')
        history = self.store.q('SELECT decision FROM knowledge_reviews ORDER BY seq')
        self.assertEqual([r['decision'] for r in history],
                         ['approved', 'rejected', 'changes_requested'])

    def test_identical_retry_and_get_produce_no_db_writes(self):
        payload = self.decision()
        self.assertEqual(self.admin.call('POST', self.review_path, payload)[0], 200)
        count = self.store.db.total_changes
        self.assertEqual(self.admin.call('POST', self.review_path, payload)[0], 200)
        self.assertEqual(self.store.db.total_changes, count)
        self.state()
        self.assertEqual(self.store.db.total_changes, count)
        self.assertEqual(self.count(), 1)

    def test_review_history_is_authenticated_read_only_and_bounded(self):
        for i in range(35):
            self.assertEqual(self.admin.call('POST', self.review_path,
                self.decision('approved' if i % 2 == 0 else 'rejected',
                              '%032x' % (i + 1)))[0], 200)
        total = self.store.db.total_changes
        status, result = self.admin.call('GET', self.review_path)
        self.assertEqual(status, 200, result)
        self.assertEqual(len(result['items']), 30)
        self.assertEqual(result['items'][0]['request_id'], '%032x' % 35)
        self.assertFalse(result['stale'])
        self.assertEqual(self.store.db.total_changes, total)
        self.assertEqual(Client(self.live.base).call('GET', self.review_path)[0], 401)
        self.assertEqual(self.token_client('knowledge_review').call(
            'GET', self.review_path)[0], 403)

    def test_reused_request_id_for_different_decision_or_actor_is_conflict(self):
        item = self.decision()
        self.assertEqual(self.admin.call('POST', self.review_path, item)[0], 200)
        self.assertEqual(self.admin.call('POST', self.review_path,
                                         dict(item, decision='rejected'))[0], 409)
        other = self.token_client('knowledge_review')
        self.assertEqual(other.call('POST', self.review_path, item)[0], 409)
        self.assertEqual(self.count(), 1)

    def test_modified_source_marks_prior_approval_stale_never_resurrects(self):
        self.assertEqual(self.admin.call('POST', self.review_path,
                                         self.decision())[0], 200)
        self.assertEqual(self.admin.call('POST', '/api/v1/collections/reviews/documents',
                                         {'documents': [{'id': 'document-1',
                                                         'body': '改訂された文献'}]})[0], 200)
        latest = self.state()
        self.assertTrue(latest['stale'])
        self.assertTrue(latest['reviews']['0']['stale'])
        self.assertEqual(latest['reviews']['0']['status'], 'unreviewed')
        self.assertEqual(latest['reviews']['0']['previous_decision'], 'approved')
        self.assertEqual(self.admin.call('POST', self.review_path,
                                         self.decision('approved', 'b'*32))[0], 409)
        self.assertEqual(self.admin.call('POST', self.review_path,
                                         self.decision())[0], 409)
        self.assertEqual(self.count(), 1)

    def test_bad_item_index_untrusted_actor_and_review_fields_rejected(self):
        base = self.decision()
        for change in ({'item_index': True}, {'item_index': 12}, {'item_index': 1},
                       {'decision': 'factual'}, {'source_revision': '0'*64},
                       {'request_id': 'bad'}, {'reviewer': 'admin'}):
            with self.subTest(change=change):
                payload = dict(base, **change)
                status, _ = self.admin.call('POST', self.review_path, payload)
                self.assertEqual(status, 409 if change.get('source_revision') else 400)
        self.assertEqual(self.count(), 0)

    def test_distinct_review_scope_and_session_csrf(self):
        self.assertEqual(Client(self.live.base).call('POST',
                         self.review_path, self.decision())[0], 401)
        for scope in ('rw', 'ro', 'analysis', 'pdf_analysis', 'pdf_import',
                      'published', 'knowledge_propose'):
            with self.subTest(scope=scope):
                self.assertEqual(self.token_client(scope).call(
                    'POST', self.review_path, self.decision())[0], 403)
        reviewer = self.token_client('knowledge_review')
        self.assertEqual(reviewer.call('POST', self.review_path,
                                      self.decision())[0], 200)
        self.assertEqual(reviewer.call('GET', self.path)[0], 403)
        self.assertEqual(reviewer.call('GET', '/api/v1/collections')[0], 403)
        self.assertEqual(reviewer.call('GET', '/api/v1/documents/%d' % self.doc_id)[0], 403)
        self.assertEqual(reviewer.call('POST', self.path, {})[0], 403)
        self.assertEqual(reviewer.call('POST',
                         '/api/v1/documents/%d/analyses' % self.doc_id, {})[0], 403)
        self.assertTrue(self.state()['reviews']['0']['reviewer'].startswith('device:'))
        self.assertEqual(self.admin.call('POST', self.review_path,
                                         self.decision('rejected', 'b'*32),
                                         headers={'X-CSRF-Token': 'bad'})[0], 403)

    def test_deleting_source_document_cascades_review_history(self):
        self.assertEqual(self.admin.call('POST', self.review_path,
                                         self.decision())[0], 200)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.admin.call('DELETE',
                         '/api/v1/documents/%d' % self.doc_id)[0], 200)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.admin.call('GET', self.review_path)[0], 400)

    def test_cross_document_review_proposal_is_rejected(self):
        self.assertEqual(self.admin.call('POST', '/api/v1/collections/reviews/documents',
                                         {'documents': [{'id': 'another', 'body': BODY}]})[0], 200)
        other = next(r['id'] for r in self.store.list_documents('reviews')['items']
                     if r['id'] != self.doc_id)
        path = '/api/v1/documents/%d/knowledge-proposals/human-sample/reviews' % other
        self.assertEqual(self.admin.call('POST', path, self.decision())[0], 400)
        self.assertEqual(self.count(), 0)

    def test_local_review_token_is_distinct_and_loopback_only(self):
        auth = self.live.app.auth
        token = auth.local_token('knowledge_review')
        self.assertNotEqual(token, auth.local_token('knowledge_propose'))
        self.assertEqual(auth.device_for_token(token, '127.0.0.1')['scopes'],
                         'knowledge_review')
        self.assertIsNone(auth.device_for_token(token, '192.168.1.13'))
        c = Client(self.live.base)
        c.token = token
        self.assertEqual(c.call('POST', self.review_path, self.decision())[0], 200)
        self.assertEqual(c.call('GET', self.path)[0], 403)

    def test_same_uid_review_socket_is_isolated(self):
        from qnaplibrary.local_auth import LocalAuthServer, connect
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch('qnaplibrary.local_auth.socket_path',
                            side_effect=lambda port, scope='read': Path(tmp) / (scope + '.sock')):
                listener = LocalAuthServer(self.live.app.auth, 17871, 'knowledge_review')
                try:
                    token = connect(17871, 'knowledge_review')['server_token']
                    self.assertEqual(token, self.live.app.auth.local_token('knowledge_review'))
                finally:
                    listener.close()


class ReviewAddonCredentialTests(unittest.TestCase):
    def test_explicit_remote_review_token_only(self):
        addon = AddonClient('/tmp/pb-k2-connection')
        settings = {'server_url': 'https://192.168.1.14:17871', 'server_token': 'read',
                    'knowledge_server_token': 'propose',
                    'knowledge_review_token': 'review-only'}
        route = '/api/v1/documents/9/knowledge-proposals/kjob-1/reviews'
        with mock.patch.object(addon, 'settings', return_value=settings), mock.patch(
                'qnaplibrary.addon_client.request_json', return_value={'ok': True}) as send:
            addon.data('POST', route, {})
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer review-only')
            addon.data('GET', '/api/v1/documents/9/knowledge-proposals')
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer read')
            addon.data('POST', '/api/v1/documents/9/knowledge-proposals', {})
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer propose')
        with mock.patch.object(addon, 'settings', return_value={
                'server_url': settings['server_url'], 'server_token': 'read'}):
            with self.assertRaises(AddonError):
                addon.data('POST', route, {})

    def test_local_review_write_requests_review_socket(self):
        addon = AddonClient('/tmp/pb-k2-connection')
        route = '/api/v1/documents/9/knowledge-proposals/kjob-1/reviews'
        with mock.patch.object(addon, 'settings', return_value={
                'auth_method': 'local_peer', 'server_url': 'http://127.0.0.1:17871',
                'server_token': 'read'}), mock.patch(
                    'qnaplibrary.local_auth.connect', return_value={
                        'server_url': 'http://127.0.0.1:17871',
                        'server_token': 'qlv_mock'}) as connect, mock.patch(
                    'qnaplibrary.addon_client.request_json', return_value={'ok': True}) as send:
            addon.data('POST', route, {})
            connect.assert_called_once_with(17871, 'knowledge_review')
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer qlv_mock')


if __name__ == '__main__':
    unittest.main()
