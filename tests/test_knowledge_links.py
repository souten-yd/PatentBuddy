"""K3b: real SQLite and HTTP tests for two explicit, scoped hypothesis actions."""
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
BODY = '🧪高温では素早く加速し、低温ではゆっくり減速する。'
QUOTE = '低温ではゆっくり減速する。'


class KnowledgeLinksAPITests(unittest.TestCase):
    def setUp(self):
        self.live = LiveServer()
        self.addCleanup(self.live.close)
        self.admin = Client(self.live.base)
        self.admin.login_setup()
        self.store = self.live.app.store
        status, response = self.admin.call('POST', '/api/v1/collections', {'name': 'links-test'})
        self.assertEqual(status, 200, response)
        status, response = self.admin.call(
            'POST', '/api/v1/collections/links-test/documents',
            {'documents': [
                {'id': 'A', 'title': '源文献A', 'body': BODY},
                {'id': 'B', 'title': '対象文献B', 'body': '既存構造の参考文献。'},
                {'id': 'C', 'title': '別の文献C', 'body': '代替案の説明。'},
            ]},
        )
        self.assertEqual(status, 200, response)
        docs = self.store.list_documents('links-test')['items']
        ids = {row['ext_id']: row['id'] for row in docs}
        self.source_id, self.target_id, self.other_id = [ids[k] for k in ('A', 'B', 'C')]
        self.source = self.store.get_document(self.source_id)
        self.target = self.store.get_document(self.target_id)
        self.proposal_id = 'link-test-proposal'
        entry = {
            'kind': 'principle', 'statement': '温度低下時の減速を抑える',
            'evidence': {'quote': QUOTE}, 'conditions': ['温度監視'],
            'limitations': ['他方式での有効性は未確認'],
        }
        proposal = _from_model(self.source, PROOF, json.dumps({'items': [entry]},
                                                              ensure_ascii=False))
        self.save_path = '/api/v1/documents/%d/knowledge-proposals' % self.source_id
        status, response = self.admin.call('POST', self.save_path, {
            'id': self.proposal_id, 'kind': 'knowledge',
            'source_revision': self.source['revision'], 'content': serialize(proposal),
        })
        self.assertEqual(status, 200, response)
        self.register_path = self.save_path + '/' + self.proposal_id + '/links'
        self.list_path = '/api/v1/documents/%d/knowledge-links' % self.source_id
        self.map_path = '/api/v1/documents/%d/knowledge-map' % self.source_id
        self.target_path = '/api/v1/documents/%d/link-target' % self.target_id
        self.payload = {
            'item_index': 0, 'source_revision': self.source['revision'],
            'target_doc_id': self.target_id, 'target_revision': self.target['revision'],
            'relation': 'substitution', 'confirm_evidence': True,
        }

    def approve_source(self, *, status='approved', request_id='a' * 32):
        path = self.save_path + '/' + self.proposal_id + '/reviews'
        code, result = self.admin.call('POST', path, {
            'request_id': request_id, 'item_index': 0,
            'source_revision': self.source['revision'], 'decision': status,
        })
        self.assertEqual(code, 200, result)

    def create_link(self, payload=None):
        status, value = self.admin.call('POST', self.register_path,
                                        self.payload if payload is None else payload)
        self.assertEqual(status, 200, value)
        return value

    def decide(self, identifier, revision, decision='approved'):
        return self.admin.call('POST', '/api/v1/knowledge-links/%s/review' % identifier, {
            'decision': decision, 'expected_graph_revision': revision,
            'confirm_evidence': True,
        })

    def token_client(self, scope):
        status, result = self.admin.call('POST', '/api/devices', {
            'name': 'link-' + scope, 'scopes': scope,
        })
        self.assertEqual(status, 200, result)
        client = Client(self.live.base)
        client.token = result['token']
        return client

    def test_explicit_two_step_review_keeps_inference_out_of_default_map(self):
        self.approve_source()
        registered = self.create_link()
        self.assertTrue(registered['id'].startswith('klink_'))
        self.assertEqual(registered['basis'], 'inferred')
        self.assertEqual(registered['review_status'], 'unreviewed')
        self.assertEqual(self.store.one(
            'SELECT COUNT(*) FROM knowledge_link_origins')[0], 1)
        self.assertEqual(self.store.one(
            'SELECT basis FROM graph_edges WHERE id=?', (registered['id'],))[0],
            'inferred')
        self.assertEqual(self.admin.call('GET', self.map_path + '?include_links=true')[1]['edges'], [
            e for e in self.admin.call('GET', self.map_path + '?include_links=true')[1]['edges']
            if e['basis'] != 'inferred'])
        status, decision = self.decide(registered['id'], registered['graph_revision'])
        self.assertEqual(status, 200, decision)
        self.assertEqual(decision['basis'], 'inferred')
        self.assertEqual(decision['review_status'], 'approved')
        _, normal = self.admin.call('GET', self.map_path)
        self.assertFalse(any(e['basis'] == 'inferred' for e in normal['edges']))
        _, opt = self.admin.call('GET', self.map_path + '?include_links=true')
        link = next(e for e in opt['edges'] if e['basis'] == 'inferred')
        self.assertEqual(link['relation'], 'substitution')
        self.assertEqual(link['evidence']['quote'], QUOTE)
        self.assertTrue(opt['include_links'])
        self.assertIn('model_inference', json.loads(
            self.store.one("SELECT content FROM document_analyses WHERE id=?",
                           (self.proposal_id,))[0])['items'][0]['basis'])

    def test_unapproved_rejected_or_revoked_source_cannot_register_or_approve(self):
        self.assertEqual(self.admin.call('POST', self.register_path, self.payload)[0], 409)
        self.approve_source()
        link = self.create_link()
        self.approve_source(status='rejected', request_id='b' * 32)
        self.assertEqual(self.admin.call('POST', self.register_path, self.payload)[0], 409)
        self.assertEqual(self.decide(link['id'], link['graph_revision'])[0], 409)
        self.assertEqual(self.store.one(
            'SELECT review_status FROM graph_edges WHERE id=?', (link['id'],))[0],
            'unreviewed')

    def test_revoked_k2_approval_invalidates_previously_approved_link(self):
        self.approve_source()
        link = self.create_link()
        self.assertEqual(self.decide(link['id'], link['graph_revision'])[0], 200)
        self.assertEqual(self.admin.call('GET', self.list_path)[1]['items'][0]
                         ['review_status'], 'approved')
        self.approve_source(status='rejected', request_id='b' * 32)
        status, result = self.admin.call('GET', self.list_path)
        self.assertEqual(status, 200, result)
        row = result['items'][0]
        self.assertTrue(row['stale'])
        self.assertEqual(row['review_status'], 'unreviewed')
        self.assertEqual(row['previous_review_status'], 'approved')
        status, map_data = self.admin.call('GET', self.map_path + '?include_links=true')
        self.assertEqual(status, 200, map_data)
        self.assertFalse(any(edge['basis'] == 'inferred' for edge in map_data['edges']))

    def test_k2_reapproval_does_not_reactivate_old_link_approval(self):
        self.approve_source()
        old_link = self.create_link()
        self.assertEqual(self.decide(old_link['id'], old_link['graph_revision'])[0], 200)
        self.approve_source(status='rejected', request_id='b' * 32)
        self.approve_source(status='approved', request_id='c' * 32)
        listed = self.admin.call('GET', self.list_path)[1]['items']
        self.assertEqual(len(listed), 1)
        self.assertTrue(listed[0]['stale'])
        self.assertEqual(listed[0]['review_status'], 'unreviewed')
        self.assertEqual(listed[0]['previous_review_status'], 'approved')
        self.assertFalse(any(e['basis'] == 'inferred'
                             for e in self.admin.call('GET',
                                 self.map_path + '?include_links=true')[1]['edges']))
        new_link = self.create_link()
        self.assertNotEqual(new_link['id'], old_link['id'])
        self.assertEqual(new_link['review_status'], 'unreviewed')
        self.assertEqual(self.decide(new_link['id'], new_link['graph_revision'])[0], 200)
        visible = self.admin.call('GET', self.map_path + '?include_links=true')[1]['edges']
        self.assertEqual(sum(e['basis'] == 'inferred' for e in visible), 1)

    def test_idempotent_registration_does_not_write_on_retry(self):
        self.approve_source()
        first = self.create_link()
        changes = self.store.db.total_changes
        retry = self.create_link()
        self.assertEqual(first, retry)
        self.assertEqual(self.store.db.total_changes, changes)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM knowledge_link_origins')[0], 1)

    def test_version_guard_on_review_and_reject_preserves_inferred(self):
        self.approve_source()
        link = self.create_link()
        self.assertEqual(self.decide(link['id'], 'f' * 32)[0], 409)
        status, reviewed = self.decide(link['id'], link['graph_revision'], 'rejected')
        self.assertEqual(status, 200, reviewed)
        self.assertEqual(reviewed['review_status'], 'rejected')
        self.assertEqual(self.decide(link['id'], link['graph_revision'])[0], 409)
        self.assertEqual(self.store.one(
            'SELECT basis FROM graph_edges WHERE id=?', (link['id'],))[0], 'inferred')

    def test_source_and_target_changes_fail_closed_even_on_revert(self):
        self.approve_source()
        link = self.create_link()
        self.assertEqual(self.admin.call('POST', '/api/v1/collections/links-test/documents',
            {'documents': [{'id': 'B', 'title': '対象文献B', 'body': '変更された対象資料'}]})[0], 200)
        self.assertEqual(self.decide(link['id'], link['graph_revision'])[0], 409)
        self.assertEqual(self.store.one(
            'SELECT stale FROM graph_edges WHERE id=?', (link['id'],))[0], 1)
        for body in ('編集された元文献', BODY):
            self.assertEqual(self.admin.call('POST', '/api/v1/collections/links-test/documents',
                {'documents': [{'id': 'A', 'title': '源文献A', 'body': body}]})[0], 200)
        self.assertEqual(self.admin.call('POST', self.register_path, self.payload)[0], 409)
        _, opt = self.admin.call('GET', self.map_path + '?include_links=true')
        self.assertFalse(any(e['basis'] == 'inferred' for e in opt['edges']))

    def test_exact_evidence_and_document_versions_checked(self):
        self.approve_source()
        for patch in (
            {'confirm_evidence': False}, {'relation': 'citation'},
            {'relation': 'legal_conclusion'}, {'target_doc_id': self.source_id},
            {'target_revision': '0' * 64}, {'item_index': 9},
            {'item_index': True}, {'source_revision': '0' * 64},
            {'arbitrary': 'not allowed'},
        ):
            with self.subTest(patch=patch):
                payload = dict(self.payload, **patch)
                status, _ = self.admin.call('POST', self.register_path, payload)
                self.assertIn(status, (400, 409))
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM graph_edges')[0], 0)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM knowledge_link_origins')[0], 0)

    def test_lookup_does_not_expose_body_and_history_is_bounded(self):
        status, target = self.admin.call('GET', self.target_path)
        self.assertEqual(status, 200, target)
        self.assertEqual(target['revision'], self.target['revision'])
        self.assertNotIn('body', target)
        self.approve_source()
        for relation in ('problem', 'solution', 'effect', 'substitution'):
            self.create_link(dict(self.payload, relation=relation))
        changes = self.store.db.total_changes
        for _ in range(3):
            status, links = self.admin.call('GET', self.list_path)
            self.assertEqual(status, 200, links)
            self.assertEqual(len(links['items']), 4)
            self.assertTrue(all(v['basis'] == 'inferred' for v in links['items']))
        self.assertEqual(self.store.db.total_changes, changes)

    def test_writer_scope_is_post_only_and_no_other_token_may_write(self):
        anonymous = Client(self.live.base)
        self.assertEqual(anonymous.call('POST', self.register_path, self.payload)[0], 401)
        for scope in ('ro', 'rw', 'analysis', 'pdf_analysis', 'knowledge_propose',
                      'knowledge_review', 'published'):
            with self.subTest(scope=scope):
                token = self.token_client(scope)
                self.assertEqual(token.call('POST', self.register_path, self.payload)[0], 403)
        scoped = self.token_client('knowledge_link')
        self.assertEqual(scoped.call('GET', self.list_path)[0], 403)
        self.assertEqual(scoped.call('GET', self.target_path)[0], 403)
        self.assertEqual(scoped.call('GET', '/api/v1/collections')[0], 403)
        self.assertEqual(scoped.call('POST', self.save_path, {})[0], 403)
        self.assertEqual(scoped.call('POST',
                                    self.save_path + '/' + self.proposal_id + '/reviews',
                                    {})[0], 403)
        self.approve_source()
        self.assertEqual(scoped.call('POST', self.register_path, self.payload)[0], 200)
        self.assertEqual(self.admin.call('POST', self.register_path, self.payload,
                          headers={'X-CSRF-Token': 'invalid'})[0], 403)

    def test_same_user_local_token_restricted_to_loopback(self):
        auth = self.live.app.auth
        token = auth.local_token('knowledge_link')
        self.assertTrue(token.startswith('qle_'))
        self.assertNotEqual(token, auth.local_token('knowledge_review'))
        self.assertEqual(auth.device_for_token(token, '127.0.0.1')['scopes'],
                         'knowledge_link')
        self.assertIsNone(auth.device_for_token(token, '192.168.1.7'))


class LinkAddonCredentialTests(unittest.TestCase):
    def test_link_post_uses_only_explicit_remote_link_token(self):
        c = AddonClient('/tmp/pb-link-config')
        args = {'server_url': 'https://192.168.1.10:17871',
                'server_token': 'read-secret',
                'knowledge_review_token': 'review-secret',
                'knowledge_link_token': 'link-secret'}
        create = '/api/v1/documents/4/knowledge-proposals/abc-4/links'
        decision = '/api/v1/knowledge-links/klink_' + 'a' * 64 + '/review'
        with mock.patch.object(c, 'settings', return_value=args), mock.patch(
                'qnaplibrary.addon_client.request_json', return_value={'ok': True}) as send:
            c.data('POST', create, {})
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer link-secret')
            c.data('POST', decision, {})
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer link-secret')
            c.data('GET', '/api/v1/documents/4/knowledge-links')
            self.assertEqual(send.call_args.args[4]['Authorization'], 'Bearer read-secret')
        with mock.patch.object(c, 'settings', return_value={
                'server_url': args['server_url'],
                'server_token': args['server_token']}):
            with self.assertRaises(AddonError):
                c.data('POST', create, {})


if __name__ == '__main__':
    unittest.main()
