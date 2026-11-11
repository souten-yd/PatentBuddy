import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from qnaplibrary.addon_client import AddonClient, AddonError
from qnaplibrary.addon_embedding_jobs import EmbeddingJobs
from tests.helpers import Client, LiveServer

MODEL = 'a' * 64


class Host:
    gate = None
    fail_terminal = False
    model = MODEL
    count = 0
    events = []

    def __init__(self, client, headers):
        self.owner = 'user:' + headers.get('owner', '1')
        self.aborted = threading.Event(); self.request_id = self.lease_id = None
        self.resource_changed = lambda: None
    def call(self, *args):
        return {'text.embed': dict(available=True, model_ref=self.model,
            execution_policy='local_only', revision_kind='host_file_metadata_v1')}
    def create_job(self, title):
        Host.count += 1; self.job_id = 'embed-test-%d' % Host.count; return self.job_id
    def acquire_cpu(self):
        self.request_id = 'request'; self.resource_changed()
        self.lease_id = 'lease'; self.resource_changed()
    def release_cpu(self):
        Host.events.append('release'); self.lease_id = self.request_id = None
    def progress(self, *args): pass
    def heartbeat(self): return dict(status='running', cancel_requested=False)
    def abort(self): self.aborted.set()
    def retrieval(self, capability, inputs):
        if Host.gate:
            while not Host.gate.wait(.01):
                if self.aborted.is_set(): raise AddonError(409, 'canceled')
        return dict(model_ref=self.model, revision_kind='host_file_metadata_v1', execution_policy='local_only',
                    dimensions=2, vectors=[[1, 0] for _ in inputs])
    def finish(self, status, result=None):
        Host.events.append('finish')
        if Host.fail_terminal: raise AddonError(502, 'offline')
        return dict(terminal_matches=True, status=status)


class EmbeddingJobTests(unittest.TestCase):
    def setUp(self):
        self.hub = LiveServer(); self.temp = tempfile.TemporaryDirectory()
        admin = Client(self.hub.base); admin.login_setup()
        admin.call('POST', '/api/v1/collections', {'name': 'embedding-test'})
        admin.call('POST', '/api/v1/collections/embedding-test/documents', {'documents': [{'id': 'one', 'body': '秘密の電池技術。'}]})
        config = Path(self.temp.name) / 'connection.json'
        config.write_text(json.dumps({'server_url': self.hub.base, 'server_token': self.hub.app.auth.local_token('embedding')})); config.chmod(0o600)
        Host.gate = None; Host.fail_terminal = False; Host.model = MODEL; Host.events = []
        self.patch = patch('qnaplibrary.addon_embedding_jobs.ComputeHostSession', Host); self.patch.start()
        self.client = AddonClient(self.temp.name)
        self.jobs = EmbeddingJobs(self.client, self.temp.name)
        self.identity = {'subject': '1'}

    def tearDown(self):
        self.jobs.close(); self.patch.stop(); self.hub.close(); self.temp.cleanup()

    def wait(self, identifier):
        end = time.monotonic() + 5
        while identifier in self.jobs.sessions and time.monotonic() < end: time.sleep(.01)
        self.assertNotIn(identifier, self.jobs.sessions)
        return self.jobs.jobs[identifier]

    def test_build_owner_and_private_metadata_and_cleanup_order(self):
        job = self.jobs.start({}); state = self.wait(job['id'])
        self.assertEqual(state['status'], 'succeeded'); self.assertFalse(state['host_sync_pending'])
        self.assertEqual(Host.events[-2:], ['release', 'finish'])
        self.assertEqual(self.hub.app.store.one('SELECT count(*) FROM host_vectors')[0], 1)
        self.assertEqual(self.jobs.list({'subject': '2'})['items'], [])
        for method in (lambda: self.jobs.cancel(job['id'], {'subject': '2'}),
                       lambda: self.jobs.reconcile({'owner': '2'}, job['id']),
                       lambda: self.jobs.forget(job['id'], {'subject': '2'})):
            with self.assertRaises(AddonError): method()
        state_text = self.jobs.path.read_text()
        self.assertNotIn('秘密', state_text); self.assertNotIn(self.client.settings()['server_token'], state_text)
        self.jobs.forget(job['id'], self.identity)
        self.assertEqual(self.hub.app.store.one('SELECT count(*) FROM host_vectors')[0], 1)

    def test_cancel_reconcile_then_resume_and_model_change(self):
        Host.gate = threading.Event(); Host.fail_terminal = True
        job = self.jobs.start({})
        with self.assertRaises(AddonError): self.jobs.start({})
        self.jobs.cancel(job['id'], self.identity)
        state = self.wait(job['id'])
        self.assertEqual(state['status'], 'canceled'); self.assertTrue(state['host_sync_pending'])
        with self.assertRaises(AddonError): self.jobs.forget(job['id'], self.identity)
        with self.assertRaises(AddonError): self.jobs.start({}, job['id'])
        Host.fail_terminal = False
        self.assertFalse(self.jobs.reconcile({}, job['id'])['host_sync_pending'])
        Host.model = 'b' * 64
        with self.assertRaises(AddonError): self.jobs.start({}, job['id'])
        Host.model = MODEL; Host.gate = None
        resumed = self.jobs.start({}, job['id'])
        self.assertEqual(self.wait(resumed['id'])['status'], 'succeeded')

    def test_restart_keeps_resources_for_reconciliation(self):
        self.jobs.jobs['a'*32] = dict(id='a'*32, host_job_id='old-job', owner='user:1', kind='embedding',
            model_ref=MODEL, status='running', lease_id='lease', request_id='request', host_sync_pending=True)
        self.jobs._save(); self.jobs.close()
        self.jobs = EmbeddingJobs(self.client, self.temp.name)
        self.assertEqual(self.jobs.jobs['a'*32]['status'], 'interrupted')
        with self.assertRaises(AddonError): self.jobs.start({})
        state = self.jobs.reconcile({}, 'a'*32)
        self.assertEqual(state['status'], 'canceled'); self.assertIsNone(state['lease_id'])
        self.assertFalse(state['host_sync_pending'])
        self.assertEqual(Host.events[-2:], ['release', 'finish'])
