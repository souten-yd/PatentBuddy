"""K1c: authenticated, revision-checked immutable knowledge proposal storage."""
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
ORIGINAL = '温度上昇では急速に加速する。温度低下ではゆっくり減速する。'
QUOTE = '温度低下ではゆっくり減速する。'
CANDIDATE = {
    'kind': 'principle',
    'statement': '状態変化の方向に応じた非対称な制御',
    'evidence': {'quote': QUOTE},
    'conditions': ['温度センサが利用できる'],
    'limitations': ['安定性は未確認'],
}


class KnowledgeStoreApiTests(unittest.TestCase):
    def setUp(self):
        self.server = LiveServer()
        self.addCleanup(self.server.close)
        self.admin = Client(self.server.base)
        self.admin.login_setup()
        self.store = self.server.app.store
        status, _ = self.admin.call('POST', '/api/v1/collections', {'name': 'knowledge-tests'})
        self.assertEqual(status, 200)
        status, _ = self.admin.call('POST', '/api/v1/collections/knowledge-tests/documents',
                                    {'documents': [{'id': 'invention-1', 'title': '実験文献',
                                                    'body': ORIGINAL}]})
        self.assertEqual(status, 200)
        self.doc_id = self.store.list_documents('knowledge-tests')['items'][0]['id']
        self.doc = self.store.get_document(self.doc_id)
        self.path = '/api/v1/documents/%d/knowledge-proposals' % self.doc_id
        proposal = _from_model(self.doc, PROOF, json.dumps({'items': [CANDIDATE]}, ensure_ascii=False))
        self.value = {'id': 'knowledge-job-1', 'kind': 'knowledge',
                      'source_revision': self.doc['revision'], 'content': serialize(proposal)}

    def token_client(self, scope):
        status, value = self.admin.call('POST', '/api/devices',
                                        {'name': 'test-' + scope, 'scopes': scope})
        self.assertEqual(status, 200)
        c = Client(self.server.base)
        c.token = value['token']
        return c

    def test_admin_save_get_and_zero_write_idempotent_retry(self):
        status, saved = self.admin.call('POST', self.path, self.value)
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved['review_status'], 'unreviewed')
        initial = self.store.db.total_changes
        status, again = self.admin.call('POST', self.path, self.value)
        self.assertEqual(status, 200, again)
        self.assertEqual(again, saved)
        self.assertEqual(self.store.db.total_changes, initial)
        status, found = self.admin.call('GET', self.path)
        self.assertEqual(status, 200)
        self.assertEqual(self.store.db.total_changes, initial)
        self.assertEqual(len(found['items']), 1)
        self.assertFalse(found['items'][0]['stale'])
        self.assertEqual(found['items'][0]['review_status'], 'unreviewed')
        self.assertEqual(json.loads(found['items'][0]['content'])['items'][0]['evidence']['quote'], QUOTE)
        self.assertEqual(self.store.one(
            "SELECT COUNT(*) FROM document_analyses WHERE kind='knowledge'")[0], 1)

    def test_only_exact_scoped_token_or_admin_may_write(self):
        anonymous = Client(self.server.base)
        self.assertEqual(anonymous.call('POST', self.path, self.value)[0], 401)
        self.assertEqual(anonymous.call('GET', self.path)[0], 401)
        for scope in ('rw', 'ro', 'analysis', 'pdf_analysis', 'pdf_import', 'published'):
            with self.subTest(scope=scope):
                client = self.token_client(scope)
                self.assertEqual(client.call('POST', self.path, self.value)[0], 403)
                self.assertEqual(client.call('GET', self.path)[0], 403 if scope == 'published' else 200)
        allowed = self.token_client('knowledge_propose')
        self.assertEqual(allowed.call('POST', self.path, self.value)[0], 200)
        self.assertEqual(allowed.call('POST', '/api/v1/documents/%d/analyses' % self.doc_id,
                                      dict(self.value, kind='summary'))[0], 403)
        self.assertEqual(allowed.call('POST', '/api/v1/collections/knowledge-tests/documents',
                                      {'documents': []})[0], 403)
        self.assertEqual(allowed.call('GET', self.path)[0], 200)

    def test_same_uid_local_token_is_isolated_and_loopback_only(self):
        authorized = self.server.app.auth.local_token('knowledge_propose')
        analysis_token = self.server.app.auth.local_token('analysis')
        self.assertIsInstance(authorized, str)
        self.assertNotEqual(authorized, analysis_token)
        self.assertEqual(self.server.app.auth.device_for_token(
            authorized, '127.0.0.1')['scopes'], 'knowledge_propose')
        self.assertIsNone(self.server.app.auth.device_for_token(authorized, '192.168.0.40'))
        client = Client(self.server.base)
        client.token = authorized
        self.assertEqual(client.call('POST', self.path, self.value)[0], 200)

    def test_unix_socket_keeps_knowledge_credential_separate(self):
        from qnaplibrary.local_auth import LocalAuthServer, connect
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch('qnaplibrary.local_auth.socket_path',
                            side_effect=lambda port, scope='read': Path(tmp) / (scope + '.sock')):
                listener = LocalAuthServer(self.server.app.auth, 17871, 'knowledge_propose')
                try:
                    token = connect(17871, 'knowledge_propose')['server_token']
                    self.assertEqual(self.server.app.auth.device_for_token(
                        token, '127.0.0.1')['scopes'], 'knowledge_propose')
                    self.assertNotEqual(token, self.server.app.auth.local_token('analysis'))
                    self.assertIsNone(self.server.app.auth.device_for_token(
                        token, '192.168.1.10'))
                finally:
                    listener.close()

    def test_forged_span_revision_basis_and_generation_rejected_atomically(self):
        cases = []
        p = copy.deepcopy(self.value)
        obj = json.loads(p['content'])
        obj['items'][0]['evidence']['quote'] = '存在しない本文'
        p['content'] = serialize(obj)
        cases.append(p)
        p = copy.deepcopy(self.value)
        obj = json.loads(p['content'])
        obj['items'][0]['basis'] = 'source_fact'
        p['content'] = serialize(obj)
        cases.append(p)
        p = copy.deepcopy(self.value)
        obj = json.loads(p['content'])
        obj['items'][0]['review_status'] = 'approved'
        p['content'] = serialize(obj)
        cases.append(p)
        p = copy.deepcopy(self.value)
        obj = json.loads(p['content'])
        obj['generation']['execution_policy'] = 'cloud'
        p['content'] = serialize(obj)
        cases.append(p)
        cases.append(dict(self.value, source_revision='0' * 64))
        cases.append(dict(self.value, content='{invalid json'))
        cases.append(dict(self.value, kind='summary'))
        for proposal in cases:
            with self.subTest(value=proposal['content'][:25]):
                status, error = self.admin.call('POST', self.path, proposal)
                expected = (409 if proposal['source_revision'] != self.doc['revision'] else 400)
                self.assertEqual(status, expected, error)
        self.assertEqual(self.store.one(
            "SELECT COUNT(*) FROM document_analyses WHERE kind='knowledge'")[0], 0)

    def test_old_document_becomes_stale_and_retry_refused(self):
        self.assertEqual(self.admin.call('POST', self.path, self.value)[0], 200)
        status, _ = self.admin.call('POST', '/api/v1/collections/knowledge-tests/documents',
                                    {'documents': [{'id': 'invention-1', 'body': '改訂された本文'}]})
        self.assertEqual(status, 200)
        status, found = self.admin.call('GET', self.path)
        self.assertEqual(status, 200)
        self.assertTrue(found['items'][0]['stale'])
        self.assertEqual(found['items'][0]['review_status'], 'unreviewed')
        self.assertEqual(self.admin.call('POST', self.path, self.value)[0], 409)

    def test_conflicting_analysis_id_must_not_overwrite(self):
        self.assertEqual(self.admin.call('POST', self.path, self.value)[0], 200)
        conflict = dict(self.value, id='knowledge-job-1')
        content = json.loads(conflict['content'])
        content['items'][0]['statement'] += '（改変）'
        conflict['content'] = serialize(content)
        self.assertEqual(self.admin.call('POST', self.path, conflict)[0], 409)
        found = self.store.one('SELECT content FROM document_analyses WHERE id=?',
                               ('knowledge-job-1',))['content']
        self.assertEqual(found, self.value['content'])

    def test_other_analysis_save_cannot_write_knowledge_kind(self):
        self.assertEqual(self.admin.call('POST',
            '/api/v1/documents/%d/analyses' % self.doc_id, self.value)[0], 400)


class KnowledgeAddonCredentialTests(unittest.TestCase):
    def test_remote_write_requires_separate_credential(self):
        addon = AddonClient('/tmp/pb-k1c-client-only')
        base = {'server_url': 'https://192.168.1.10:17871',
                'server_token': 'old-analysis-token', 'knowledge_server_token': 'knowledge-token'}
        with mock.patch.object(addon, 'settings', return_value=base), mock.patch(
                'qnaplibrary.addon_client.request_json', return_value={'ok': True}) as send:
            addon.data('POST', '/api/v1/documents/7/knowledge-proposals', {'kind': 'knowledge'})
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer knowledge-token')
            addon.data('POST', '/api/v1/documents/7/analyses', {'kind': 'summary'})
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer old-analysis-token')
        with mock.patch.object(addon, 'settings', return_value={
                'server_url': base['server_url'], 'server_token': base['server_token']}):
            with self.assertRaises(AddonError) as cm:
                addon.data('POST', '/api/v1/documents/7/knowledge-proposals', {})
            self.assertEqual(cm.exception.status, 503)

    def test_local_write_requests_knowledge_socket(self):
        addon = AddonClient('/tmp/pb-k1c-client-only')
        with mock.patch.object(addon, 'settings', return_value={
                'auth_method': 'local_peer', 'server_url': 'http://127.0.0.1:17871',
                'server_token': 'read-token'}), mock.patch(
                    'qnaplibrary.local_auth.connect', return_value={
                        'server_url': 'http://127.0.0.1:17871',
                        'server_token': 'knowledge-token'}) as connect, mock.patch(
                    'qnaplibrary.addon_client.request_json', return_value={'ok': True}) as send:
            addon.data('POST', '/api/v1/documents/7/knowledge-proposals', {})
            connect.assert_called_once_with(17871, 'knowledge_propose')
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer knowledge-token')


if __name__ == '__main__':
    unittest.main()
