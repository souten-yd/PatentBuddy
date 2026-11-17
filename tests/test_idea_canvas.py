"""K5 real ResearchDataHub HTTP/SQLite tests: explicit human Idea save/edit."""
import json
import unittest
from unittest import mock

from qnaplibrary.addon_client import AddonClient, AddonError

from qnaplibrary.knowledge_generation import _from_model, serialize
from tests.helpers import Client, LiveServer

PROOF = {
    'execution_policy': 'local_only',
    'revision_kind': 'host_process_file_metadata_v1',
    'model_ref': 'a' * 64, 'runtime_ref': 'b' * 64,
}
DOCUMENT_A = '🧪温度上昇時にファンを加速し、温度低下時はゆっくり減速する。'
DOCUMENT_B = '負荷急変時の冷却は移動平均で制御する。'
DOCUMENT_C = '高速な冷却応答には温度計測が必要である。'

CONTENT = {
    'title': '負荷変動に強い静音冷却',
    'problem': '頻繁なファン回転変動による騒音を減らす',
    'solution': '加熱方向は速く冷却方向は緩やかな追従を仮説として試す',
    'effect': '過渡的な騒音低減を予測するが未検証',
    'conditions': '適切な温度センサと評価環境',
    'limitations': '異分野の部品に適用可能かは未調査',
}


class IdeaCanvasHTTPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveServer()
        self.addCleanup(self.live.close)
        self.store = self.live.app.store
        self.admin = Client(self.live.base)
        self.admin.login_setup()
        status, result = self.admin.call('POST', '/api/v1/collections',
                                         {'name': 'idea-test'})
        self.assertEqual(status, 200, result)
        status, result = self.admin.call('POST',
            '/api/v1/collections/idea-test/documents', {
                'documents': [
                    {'id': 'a', 'title': '冷却特許A', 'body': DOCUMENT_A},
                    {'id': 'b', 'title': '冷却規格B', 'body': DOCUMENT_B},
                    {'id': 'c', 'title': '温度技術C', 'body': DOCUMENT_C},
                ],
            })
        self.assertEqual(status, 200, result)
        docs = self.store.list_documents('idea-test')['items']
        self.ids = {row['ext_id']: row['id'] for row in docs}
        self.documents = {key: self.store.get_document(value)
                          for key, value in self.ids.items()}
        self.sources = [
            self._approve('a', '上昇方向の高速応答', '温度上昇時にファンを加速し', 1),
            self._approve('b', '急変時の平均化', '移動平均で制御する', 2),
        ]
        self.payload = self._payload()

    def _approve(self, key, statement, quote, number):
        doc = self.documents[key]
        proposal_id = 'idea-k5-proposal-%d' % number
        proposal = _from_model(doc, PROOF, json.dumps({'items': [{
            'kind': 'principle',
            'statement': statement,
            'evidence': {'quote': quote},
            'conditions': ['温度計測'],
            'limitations': ['追加の実験が必要'],
        }]}, ensure_ascii=False))
        path = '/api/v1/documents/%d/knowledge-proposals' % doc['id']
        status, result = self.admin.call('POST', path, {
            'id': proposal_id, 'kind': 'knowledge',
            'source_revision': doc['revision'], 'content': serialize(proposal),
        })
        self.assertEqual(status, 200, result)
        status, result = self.admin.call('POST', path + '/' + proposal_id + '/reviews', {
            'request_id': '%032x' % number, 'item_index': 0,
            'source_revision': doc['revision'], 'decision': 'approved',
        })
        self.assertEqual(status, 200, result)
        return {'proposal_id': proposal_id, 'item_index': 0}

    def _payload(self, number=20):
        status, cmp = self.admin.call('POST', '/api/v1/knowledge/compare', {
            'items': self.sources,
        })
        self.assertEqual(status, 200, cmp)
        return {
            'request_id': '%032x' % number,
            'sources': [{
                key: item[key] for key in (
                    'proposal_id', 'item_index', 'doc_id',
                    'source_revision', 'source_epoch', 'review_seq',
                )
            } for item in cmp['items']],
            'content': dict(CONTENT),
            'confirm_manual': True,
        }

    def _create(self, payload=None):
        status, result = self.admin.call('POST', '/api/v1/ideas',
                                         self.payload if payload is None else payload)
        self.assertEqual(status, 200, result)
        return result

    def _detail(self, identifier):
        status, value = self.admin.call('GET', '/api/v1/ideas/' + identifier)
        self.assertEqual(status, 200, value)
        return value

    def _edit(self, identifier, version, content=None, request=21):
        return self.admin.call('PUT', '/api/v1/ideas/' + identifier, {
            'request_id': '%032x' % request, 'expected_version': version,
            'content': content or dict(CONTENT), 'confirm_manual': True,
        })

    def _token(self, scope):
        status, device = self.admin.call('POST', '/api/devices', {
            'name': 'k5-' + scope, 'scopes': scope,
        })
        self.assertEqual(status, 200, device)
        client = Client(self.live.base)
        client.token = device['token']
        return client

    def test_user_create_then_read_immutable_evidence_history(self):
        created = self._create()
        self.assertEqual(created['version'], 1)
        self.assertFalse(created['retry'])
        self.assertRegex(created['id'], r'^idea_[a-f0-9]{32}$')
        current = self._detail(created['id'])
        self.assertEqual(current['state'], 'manual_draft')
        self.assertEqual(current['basis'], 'manual_hypothesis')
        self.assertEqual(current['content'], CONTENT)
        self.assertEqual(len(current['sources']), 2)
        self.assertEqual(current['sources'][0]['evidence']['quote'],
                         '温度上昇時にファンを加速し')
        self.assertEqual(current['sources'][0]['status'],
                         'current_approved_inference')
        self.assertEqual(len(current['history']), 1)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM idea_versions')[0], 1)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM idea_sources')[0], 2)
        status, listed = self.admin.call('GET', '/api/v1/ideas')
        self.assertEqual(status, 200, listed)
        self.assertEqual(listed['items'][0]['id'], created['id'])

    def test_user_edit_uses_append_only_version_and_preserves_sources(self):
        created = self._create()
        revised = dict(CONTENT, title='静音制御の次の仮説')
        status, result = self._edit(created['id'], 1, revised)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['version'], 2)
        current = self._detail(created['id'])
        self.assertEqual(current['content']['title'], revised['title'])
        self.assertEqual([h['version'] for h in current['history']], [2, 1])
        stored = self.store.q(
            'SELECT version,content FROM idea_versions WHERE idea_id=? ORDER BY version',
            (created['id'],))
        self.assertEqual(len(stored), 2)
        self.assertEqual(json.loads(stored[0]['content'])['title'], CONTENT['title'])
        self.assertEqual(json.loads(stored[1]['content'])['title'], revised['title'])
        self.assertEqual(self.store.one(
            'SELECT COUNT(*) FROM idea_sources WHERE idea_id=?', (created['id'],))[0], 2)
        self.assertEqual(self._edit(created['id'], 1, dict(CONTENT), request=22)[0], 409)

    def test_create_and_update_retries_are_zero_write_and_collision_conflicts(self):
        first = self._create()
        changes = self.store.db.total_changes
        retried = self._create()
        self.assertTrue(retried['retry'])
        self.assertEqual(retried['id'], first['id'])
        self.assertEqual(self.store.db.total_changes, changes)
        bad = dict(self.payload, content=dict(CONTENT, problem='別の内容'))
        self.assertEqual(self.admin.call('POST', '/api/v1/ideas', bad)[0], 409)
        updated = dict(CONTENT, problem='新たな確認内容')
        status, first_edit = self._edit(first['id'], 1, updated)
        self.assertEqual(status, 200, first_edit)
        changes = self.store.db.total_changes
        status, retried_edit = self._edit(first['id'], 1, updated)
        self.assertEqual(status, 200, retried_edit)
        self.assertTrue(retried_edit['retry'])
        self.assertEqual(self.store.db.total_changes, changes)
        self.assertEqual(self._edit(first['id'], 1, dict(CONTENT), request=21)[0], 409)

    def test_source_changed_then_reverted_stays_invalid_and_blocks_edit(self):
        created = self._create()
        for body in ('一時的に変更された別の原文', DOCUMENT_A):
            status, response = self.admin.call('POST',
                '/api/v1/collections/idea-test/documents', {
                    'documents': [{'id': 'a', 'title': '冷却特許A', 'body': body}],
                })
            self.assertEqual(status, 200, response)
        current = self._detail(created['id'])
        self.assertEqual(current['state'], 'needs_revalidation')
        self.assertTrue(current['stale'])
        self.assertEqual(current['sources'][0]['status'], 'needs_revalidation')
        self.assertEqual(current['sources'][0]['evidence']['quote'],
                         '温度上昇時にファンを加速し')
        self.assertEqual(self._edit(created['id'], 1)[0], 409)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM idea_versions')[0], 1)
        self.assertEqual(self.admin.call('POST', '/api/v1/ideas',
                                         dict(self.payload, request_id='f' * 32))[0], 409)

    def test_revocation_then_reapproval_does_not_reactivate_old_draft(self):
        created = self._create()
        doc = self.documents['b']
        url = '/api/v1/documents/%d/knowledge-proposals/%s/reviews' % (
            doc['id'], self.sources[1]['proposal_id'])
        for value, n in (('rejected', 70), ('approved', 71)):
            status, result = self.admin.call('POST', url, {
                'request_id': '%032x' % n, 'item_index': 0,
                'source_revision': doc['revision'], 'decision': value,
            })
            self.assertEqual(status, 200, result)
        self.assertTrue(self._detail(created['id'])['stale'])
        self.assertEqual(self._edit(created['id'], 1)[0], 409)
        new = self._payload(72)
        second = self._create(new)
        self.assertNotEqual(second['id'], created['id'])
        self.assertFalse(self._detail(second['id'])['stale'])

    def test_deleted_document_retains_draft_and_quote_history(self):
        created = self._create()
        status, result = self.admin.call('DELETE',
                                         '/api/v1/documents/%d' % self.ids['b'])
        self.assertEqual(status, 200, result)
        current = self._detail(created['id'])
        self.assertEqual(current['state'], 'needs_revalidation')
        self.assertEqual(current['sources'][1]['title'], '削除済み文献')
        self.assertEqual(current['sources'][1]['evidence']['quote'],
                         '移動平均で制御する')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM idea_drafts')[0], 1)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM idea_sources')[0], 2)

    def test_no_writes_from_list_or_read(self):
        created = self._create()
        changes = self.store.db.total_changes
        for _ in range(3):
            self.assertEqual(self.admin.call('GET', '/api/v1/ideas')[0], 200)
            self.assertEqual(self.admin.call('GET',
                                             '/api/v1/ideas/' + created['id'])[0], 200)
        self.assertEqual(self.store.db.total_changes, changes)

    def test_invalid_input_rejected_before_any_writes(self):
        for update in (
            {'confirm_manual': False},
            {'request_id': 'wrong'},
            {'content': dict(CONTENT, title='')},
            {'content': dict(CONTENT, solution='')},
            {'content': dict(CONTENT, title='z' * 161)},
            {'sources': self.payload['sources'][:1]},
            {'sources': self.payload['sources'] * 2},
            {'extra': 'not allowed'},
        ):
            with self.subTest(update=update):
                data = dict(self.payload, **update)
                self.assertEqual(self.admin.call('POST', '/api/v1/ideas', data)[0], 400)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM idea_drafts')[0], 0)
        self.assertEqual(self.admin.call('GET', '/api/v1/ideas/idea_' +
                                         'x' * 32)[0], 400)
        self.assertEqual(self.admin.call('GET', '/api/v1/ideas?limit=0')[0], 400)

    def test_scopes_are_strict_and_admin_csrf_required(self):
        anon = Client(self.live.base)
        self.assertEqual(anon.call('GET', '/api/v1/ideas')[0], 401)
        self.assertEqual(anon.call('POST', '/api/v1/ideas', self.payload)[0], 401)
        for scope in ('ro', 'rw', 'analysis', 'pdf_import', 'published',
                      'knowledge_propose', 'knowledge_review', 'knowledge_link'):
            with self.subTest(scope=scope):
                user = self._token(scope)
                self.assertEqual(user.call('POST', '/api/v1/ideas', self.payload)[0], 403)
        special = self._token('idea_write')
        self.assertEqual(special.call('GET', '/api/v1/ideas')[0], 403)
        self.assertEqual(special.call('POST', '/api/v1/knowledge/search',
                                      {'q': '温度'})[0], 403)
        self.assertEqual(special.call('POST', '/api/v1/ideas', self.payload)[0], 200)
        self.assertEqual(special.call('POST', '/api/v1/knowledge/compare',
                                      {'items': self.sources})[0], 403)
        self.assertEqual(special.call('POST', '/api/v1/documents/%d/analyses' %
                                     self.ids['a'], {})[0], 403)
        self.assertEqual(self.admin.call('POST', '/api/v1/ideas',
            self.payload, headers={'X-CSRF-Token': 'not-the-real-token'})[0], 403)

    def test_local_idea_token_is_loopback_only(self):
        token = self.live.app.auth.local_token('idea_write')
        self.assertTrue(token.startswith('qlj_'))
        self.assertEqual(self.live.app.auth.device_for_token(
            token, '127.0.0.1')['scopes'], 'idea_write')
        self.assertIsNone(self.live.app.auth.device_for_token(token, '192.168.1.20'))


class IdeaAddonCredentialsTests(unittest.TestCase):
    def test_idea_writes_use_only_dedicated_token_and_reads_use_normal_read(self):
        client = AddonClient('/tmp/idea-addon-config-test')
        config = {
            'server_url': 'https://192.168.1.10:17871',
            'server_token': 'read-secret',
            'knowledge_link_token': 'link-secret',
            'knowledge_review_token': 'review-secret',
            'idea_write_token': 'idea-only-secret',
        }
        with mock.patch.object(client, 'settings', return_value=config), mock.patch(
                'qnaplibrary.addon_client.request_json', return_value={'ok': True}) as send:
            client.data('POST', '/api/v1/ideas', {})
            self.assertEqual(send.call_args.args[4]['Authorization'],
                             'Bearer idea-only-secret')
            client.data('PUT', '/api/v1/ideas/idea_' + 'a'*32, {})
            self.assertEqual(send.call_args.args[4]['Authorization'],
                             'Bearer idea-only-secret')
            client.data('GET', '/api/v1/ideas')
            self.assertEqual(send.call_args.args[4]['Authorization'],
                             'Bearer read-secret')
        with mock.patch.object(client, 'settings', return_value={
                'server_url': config['server_url'], 'server_token': config['server_token']}):
            with self.assertRaises(AddonError):
                client.data('POST', '/api/v1/ideas', {})
            with self.assertRaises(AddonError):
                client.data('PUT', '/api/v1/ideas/idea_' + 'a'*32, {})

    def test_local_idea_credential_never_falls_back_to_read_scope(self):
        client = AddonClient('/tmp/idea-addon-config-test')
        config = {
            'server_url': 'http://127.0.0.1:17871',
            'server_token': 'read-secret', 'auth_method': 'local_peer',
        }
        with mock.patch.object(client, 'settings', return_value=config), mock.patch(
                'qnaplibrary.local_auth.connect', return_value={
                    'server_url': 'http://127.0.0.1:17871',
                    'server_token': 'qlj_special-idea-secret',
                }) as connect, mock.patch(
                    'qnaplibrary.addon_client.request_json', return_value={'ok': True}) as send:
            client.data('POST', '/api/v1/ideas', {})
            self.assertEqual(connect.call_args.args, (17871, 'idea_write'))
            self.assertEqual(send.call_args.args[4]['Authorization'],
                             'Bearer qlj_special-idea-secret')
        with mock.patch.object(client, 'settings', return_value=config), mock.patch(
                'qnaplibrary.local_auth.connect', side_effect=OSError('unavailable')):
            with self.assertRaises(AddonError):
                client.data('POST', '/api/v1/ideas', {})


if __name__ == '__main__':
    unittest.main()
