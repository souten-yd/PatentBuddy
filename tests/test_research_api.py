"""HTTP contract for /api/v1/research/: auth, CSRF/Origin, validation, privacy."""
import json
import pathlib
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from qnaplibrary import debuglog
from tests.helpers import LiveServer, Client

VALUE = dict(id='a' * 32, query='ta=inverter', limit=10, confirm_public=True)
RESULT = dict(records=[dict(publication='EP1004359B1', language='en', family=None, title='Synthetic',
                            sources=['epo_ops'], cells=['IPC:H02M 1/00'])],
              provider='epo_ops', fetched=1, reported_total=5, truncated=True)
OPS_KEY = 'synthetic-ops-key-1'
OPS_SECRET = 'synthetic-ops-secret-2'
# Provider failure text repeats the query and echoes a credential-shaped value:
# neither may be stored or returned by any surface.
DETAIL = 'ops 502 q=ta%3Dinverter key=synthetic-ops-secret-2 detail-77'


def post_raw(client, path, payload, headers=None):
    """Send raw bytes the JSON client would not build (broken or oversized bodies)."""
    built = {'Content-Type': 'application/json', 'X-CSRF-Token': client.csrf or ''}
    if client.token:
        built['Authorization'] = 'Bearer ' + client.token
    built.update(headers or {})
    request = urllib.request.Request(client.base + path, data=payload, method='POST', headers=built)
    try:
        with client.opener.open(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


class ResearchApiTests(unittest.TestCase):
    def setUp(self):
        debuglog.setup('WARNING', stderr=False)
        self.server = LiveServer()
        self.addCleanup(self.server.close)
        self.base = self.server.base
        self.store = self.server.app.store
        self.admin = Client(self.base)
        self.admin.login_setup()
        self.path = '/api/v1/research/requests'

    def device(self, name, scopes):
        client = Client(self.base)
        client.token = self.server.app.auth.create_device(name, scopes)['token']
        return client

    def rows(self):
        return self.store.one('SELECT count(*) FROM research_requests')[0]

    # --- authentication ---------------------------------------------------
    def test_anonymous_is_refused_everywhere(self):
        anon = Client(self.base)
        self.assertEqual(anon.call('GET', self.path)[0], 401)
        self.assertEqual(anon.call('POST', self.path, VALUE)[0], 401)
        self.assertEqual(anon.call('GET', self.path + '/' + VALUE['id'])[0], 401)
        self.assertEqual(anon.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                   {'revision': 1, 'action': 'cancel'})[0], 401)
        self.assertEqual(self.rows(), 0)

    def test_scopes_reach_only_the_research_api(self):
        research = self.device('research-worker', 'research')
        self.assertEqual(research.call('GET', self.path)[0], 200)
        self.assertEqual(research.call('POST', self.path, VALUE)[0], 200)
        self.assertEqual(research.call('GET', self.path + '/' + VALUE['id'])[0], 200)
        self.assertEqual(research.call('GET', '/api/v1/research/snapshots')[0], 200)
        self.assertEqual(research.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                       {'revision': 1, 'action': 'cancel'})[0], 200)
        for path in ('/api/v1/collections', '/api/settings', '/api/devices', '/api/debug/bundle',
                     '/api/v1/research', '/api/v1/research/1', '/api/v1/patents', '/api/v1/schema',
                     '/api/v1/documents/1'):
            self.assertEqual(research.call('GET', path)[0], 403, path)
        for method, path, body in (('POST', '/api/v1/collections', {'name': 'nope'}),
                                   ('POST', '/api/v1/search', {'q': 'inverter'}),
                                   ('POST', '/api/v1/research', {'question': 'secret idea'}),
                                   ('POST', '/mcp', {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})):
            self.assertEqual(research.call(method, path, body)[0], 403, path)
        # Discovery belongs to the research scope, but without EPO keys it must stop
        # before any provider call, and foreign bodies are refused.
        with patch('qnaplibrary.research_discovery.search') as search:
            self.assertEqual(research.call('POST', '/api/v1/research/discover/epo',
                                           {'query': 'ta=inverter', 'limit': 10, 'confirm_public': True})[0], 409)
            self.assertEqual(research.call('POST', '/api/v1/research/discover/epo', VALUE)[0], 400)
            self.assertEqual(research.call('POST', '/api/v1/research/discover/epo',
                                           {'query': 'ta=inverter', 'limit': 10, 'confirm_public': False})[0], 403)
            search.assert_not_called()
        # No other device scope may use the research API at all.
        for scopes in ('ro', 'rw', 'published', 'analysis', 'pdf_import'):
            other = self.device('device-' + scopes, scopes)
            self.assertEqual(other.call('GET', self.path)[0], 403, scopes)
            self.assertEqual(other.call('POST', self.path, VALUE)[0], 403, scopes)
        self.assertEqual(self.admin.call('GET', self.path)[0], 200)
        self.assertEqual(self.admin.call('GET', '/api/v1/collections')[0], 200)

    # --- CSRF / Origin ----------------------------------------------------
    def test_writes_need_csrf_and_matching_origin(self):
        csrf = self.admin.csrf
        self.admin.csrf = None
        self.assertEqual(self.admin.call('POST', self.path, VALUE)[0], 403)
        self.admin.csrf = csrf + 'x'
        self.assertEqual(self.admin.call('POST', self.path, VALUE)[0], 403)
        self.assertEqual(self.rows(), 0)
        self.admin.csrf = csrf
        self.assertEqual(self.admin.call('POST', self.path, VALUE,
                                         headers={'Origin': 'http://evil.example'})[0], 403)
        self.assertEqual(self.rows(), 0)
        self.assertEqual(self.admin.call('GET', self.path, headers={'Origin': 'http://evil.example'})[0], 200)
        self.assertEqual(self.admin.call('POST', self.path, VALUE, headers={'Origin': self.base})[0], 200)
        revision = self.admin.call('GET', self.path + '/' + VALUE['id'])[1]['revision']
        self.admin.csrf = None
        self.assertEqual(self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                         {'revision': revision, 'action': 'cancel'})[0], 403)
        self.assertEqual(self.admin.call('GET', self.path + '/' + VALUE['id'])[1]['state'], 'queued')

    # --- validation -------------------------------------------------------
    def test_rejects_malformed_requests_without_writing(self):
        missing_id = dict(VALUE)
        del missing_id['id']
        bad = [missing_id, dict(VALUE, id=''), dict(VALUE, id='A' * 32), dict(VALUE, id='a' * 31),
               dict(VALUE, id='a' * 31 + 'g'), dict(VALUE, id=1), dict(VALUE, id=None),
               dict(VALUE, query=''), dict(VALUE, query='   '), dict(VALUE, query=123),
               dict(VALUE, query=['a']), dict(VALUE, query='x' * 2001), dict(VALUE, query=None),
               dict(VALUE, limit=0), dict(VALUE, limit=101), dict(VALUE, limit='10'),
               dict(VALUE, limit=10.5), dict(VALUE, limit=True), dict(VALUE, limit=None),
               dict(VALUE, confirm_public=False), dict(VALUE, confirm_public='true'),
               dict(VALUE, confirm_public=1), dict(VALUE, unexpected=1), {'query': 'ta=inverter'}]
        for value in bad:
            status, body = self.admin.call('POST', self.path, value)
            self.assertEqual(status, 400, value)
            self.assertIsInstance(body.get('error'), str)
        self.assertEqual(self.rows(), 0)
        self.assertEqual(self.admin.call('POST', self.path, [VALUE])[0], 400)
        self.assertEqual(self.admin.call('GET', self.path + '/deadbeef')[0], 400)
        self.assertEqual(self.admin.call('GET', self.path + '?cursor=zzzz')[0], 400)
        self.assertEqual(self.admin.call('GET', '/api/v1/research/snapshots?cursor=zzzz')[0], 400)
        self.assertEqual(self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition', {})[0], 400)
        self.assertEqual(self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                         {'revision': 1, 'action': 'explode'})[0], 400)
        self.assertEqual(post_raw(self.admin, self.path, b'{"query":'), 400)

    def test_accepts_boundary_values_and_rejects_oversized_body(self):
        self.assertEqual(self.admin.call('POST', self.path, dict(VALUE, query='x' * 2000))[0], 200)
        self.assertEqual(self.admin.call('POST', self.path, dict(VALUE, id='b' * 32, limit=100))[0], 200)
        self.assertEqual(self.admin.call('POST', self.path, dict(VALUE, id='c' * 32, limit=1))[0], 200)
        self.assertEqual(self.rows(), 3)
        self.assertEqual(post_raw(self.admin, self.path,
                                  json.dumps(dict(VALUE, id='d' * 32, query='q' * 40000)).encode()), 413)
        self.assertEqual(self.rows(), 3)

    def test_create_is_idempotent_and_conditions_are_immutable(self):
        first = self.admin.call('POST', self.path, VALUE)
        changes = self.store.db.total_changes
        self.assertEqual(self.admin.call('POST', self.path, VALUE), first)
        self.assertEqual(self.store.db.total_changes, changes)
        status, body = self.admin.call('POST', self.path, dict(VALUE, limit=20))
        self.assertEqual(status, 400)
        self.assertIn('different conditions', body['error'])
        self.assertEqual(self.rows(), 1)
        listed = self.admin.call('GET', self.path)[1]
        self.assertEqual([row['id'] for row in listed['items']], [VALUE['id']])
        self.assertIsNone(listed['next_cursor'])

    def test_pending_and_page_limits(self):
        for i in range(100):
            self.assertEqual(self.admin.call('POST', self.path, dict(VALUE, id='%032x' % i))[0], 200, i)
        status, body = self.admin.call('POST', self.path, dict(VALUE, id='f' * 32))
        self.assertEqual(status, 400)
        self.assertIn('limit', body['error'])
        self.assertEqual(self.rows(), 100)
        page = self.admin.call('GET', self.path)[1]
        self.assertEqual(len(page['items']), 50)
        self.assertEqual(page['items'][0]['id'], '%032x' % 99)
        self.assertEqual(page['next_cursor'], page['items'][-1]['id'])
        rest = self.admin.call('GET', self.path + '?cursor=' + page['next_cursor'])[1]
        self.assertEqual(len(rest['items']), 50)
        self.assertEqual(rest['items'][0]['id'], '%032x' % 49)
        self.assertIsNone(rest['next_cursor'])
        self.assertEqual({row['id'] for row in page['items']} & {row['id'] for row in rest['items']}, set())

    def test_transition_contract_and_worker_wakeup(self):
        self.assertEqual(self.admin.call('POST', self.path, VALUE)[0], 200)
        self.assertTrue(self.server.app.research_worker.wake.is_set())
        self.server.app.research_worker.wake.clear()
        current = self.admin.call('GET', self.path + '/' + VALUE['id'])[1]
        self.assertEqual(self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                         {'revision': current['revision'] + 5, 'action': 'retry'})[0], 400)
        self.assertEqual(self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                         {'revision': current['revision'], 'action': 'retry'})[0], 400)
        canceled = self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                   {'revision': current['revision'], 'action': 'cancel'})[1]
        self.assertEqual((canceled['state'], canceled['error']), ('canceled', ''))
        self.assertEqual(self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                         {'revision': current['revision'], 'action': 'cancel'})[0], 400)
        self.server.app.research_worker.wake.clear()
        retried = self.admin.call('POST', self.path + '/' + VALUE['id'] + '/transition',
                                  {'revision': canceled['revision'], 'action': 'retry'})[1]
        self.assertEqual((retried['state'], retried['error']), ('queued', ''))
        self.assertTrue(self.server.app.research_worker.wake.is_set())
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0], 0)

    # --- completion over HTTP (provider calls are always mocked) ----------
    def test_queue_completes_through_api_without_network(self):
        self.server.app.config.set_secret('epo_ops_key', OPS_KEY)
        self.server.app.config.set_secret('epo_ops_secret', OPS_SECRET)
        self.assertEqual(self.admin.call('POST', self.path, VALUE)[0], 200)
        with patch('qnaplibrary.research_discovery.search', return_value=RESULT) as search:
            self.assertTrue(self.server.app.research_worker.run_once())
        self.assertEqual(search.call_args.args, (VALUE['query'], VALUE['limit'], OPS_KEY, OPS_SECRET))
        row = self.admin.call('GET', self.path + '/' + VALUE['id'])[1]
        self.assertEqual((row['state'], row['error']), ('awaiting_selection', ''))
        self.assertIsNotNone(row['snapshot_id'])
        snapshot = self.admin.call('GET', '/api/v1/research/snapshots/' + row['snapshot_id'])[1]
        self.assertEqual(snapshot['discovery']['query'], VALUE['query'])
        self.assertEqual(snapshot['discovery']['requested_limit'], VALUE['limit'])
        self.assertEqual(snapshot['discovery']['reported_total'], 5)
        self.assertTrue(snapshot['discovery']['truncated'])
        self.assertEqual(snapshot['snapshot']['unique_publications'], 1)
        # Candidate snapshots only: the corpus and its documents stay untouched.
        self.assertEqual(self.store.one('SELECT count(*) FROM documents')[0], 0)
        for body in (row, self.admin.call('GET', self.path)[1], snapshot,
                     self.admin.call('GET', '/api/debug/bundle')[1]):
            self.assertNotIn(OPS_KEY, json.dumps(body))
            self.assertNotIn(OPS_SECRET, json.dumps(body))
        self.assertNotIn('lease', json.dumps(row))

    def test_provider_detail_stays_out_of_responses_and_files(self):
        self.server.app.config.set_secret('epo_ops_key', OPS_KEY)
        self.server.app.config.set_secret('epo_ops_secret', OPS_SECRET)
        self.assertEqual(self.admin.call('POST', self.path, VALUE)[0], 200)
        with patch('qnaplibrary.research_discovery.search', side_effect=RuntimeError(DETAIL)):
            self.assertTrue(self.server.app.research_worker.run_once())
        row = self.admin.call('GET', self.path + '/' + VALUE['id'])[1]
        self.assertEqual((row['state'], row['error']), ('failed', 'provider_failed'))
        bundle = self.admin.call('GET', '/api/debug/bundle')[1]
        audit = [dict(r) for r in self.store.q('SELECT actor,action,detail FROM audit')]
        self.assertIn('research.failed', [r['action'] for r in audit])
        self.store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        on_disk = b''.join(p.read_bytes() for p in sorted(pathlib.Path(self.server.app.data_dir).rglob('*'))
                           if p.is_file())
        for surface in (json.dumps(row), json.dumps(self.admin.call('GET', self.path)[1]), json.dumps(bundle),
                        json.dumps(audit), on_disk.decode('utf-8', 'replace')):
            self.assertNotIn('detail-77', surface)
        for surface in (json.dumps(row), json.dumps(self.admin.call('GET', self.path)[1]), json.dumps(bundle),
                        json.dumps(audit)):
            self.assertNotIn(OPS_SECRET, surface)
            self.assertNotIn(OPS_KEY, surface)
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0], 0)


if __name__ == '__main__':
    unittest.main()
