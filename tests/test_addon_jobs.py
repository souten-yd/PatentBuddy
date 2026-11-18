import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from qnaplibrary.addon_client import AddonClient, AddonError
from qnaplibrary.addon_jobs import AnalysisJobs
from tests.helpers import LiveServer, Client


class FakeHost:
    last = None
    gate = None
    cancel_on_control = False
    fail_terminal = False
    local_ready = True
    defer_raise_503 = False

    def __init__(self, client, headers):
        self.owner = 'user:1'; self.job_id = None; self.aborted = threading.Event()
        self.finished = []; self.entered = threading.Event(); FakeHost.last = self

    def local_available(self):
        if self.defer_raise_503:
            raise AddonError(503, 'local AI temporarily unavailable')
        return self.local_ready
    def create_job(self): self.job_id = 'host-job-' + str(time.time_ns()); return self.job_id
    def heartbeat(self): return {'host_job_id': self.job_id, 'status': 'running', 'cancel_requested': self.cancel_on_control}
    def progress(self, *args): pass
    def stream(self, messages):
        self.entered.set()
        if self.gate:
            while not self.gate.wait(.01):
                if self.aborted.is_set(): raise AddonError(409, 'canceled')
        if self.aborted.is_set(): raise AddonError(409, 'canceled')
        return '合成分析結果です。'
    def abort(self): self.aborted.set()
    def finish(self, status, result=None):
        self.finished.append((status, result))
        if self.fail_terminal: raise AddonError(502, 'connection unavailable')
        return {'status': status, 'terminal_matches': True}


class AnalysisJobsTests(unittest.TestCase):
    def setUp(self):
        self.hub = LiveServer(); self.temp = tempfile.TemporaryDirectory()
        admin = Client(self.hub.base); admin.login_setup()
        admin.call('POST', '/api/v1/collections', {'name': 'synthetic-analysis'})
        admin.call('POST', '/api/v1/collections/synthetic-analysis/documents', {'documents': [
            {'id': 'example', 'body': '秘密の合成本文', 'source': 'synthetic'}]})
        self.did = self.hub.app.store.list_documents('synthetic-analysis')['items'][0]['id']
        _, token = admin.call('POST', '/api/devices', {'name': 'synthetic-analysis', 'scopes': 'rw'})
        p = Path(self.temp.name) / 'connection.json';p.write_text(json.dumps({'server_url': self.hub.base, 'server_token': token['token']}));p.chmod(0o600)
        FakeHost.gate = None; FakeHost.cancel_on_control = False; FakeHost.fail_terminal = False
        FakeHost.local_ready = True; FakeHost.defer_raise_503 = False
        self.patch = mock.patch('qnaplibrary.addon_jobs.HostSession', FakeHost); self.patch.start()
        self.jobs = AnalysisJobs(AddonClient(self.temp.name), self.temp.name)
        self.identity = {'subject': '1', 'actor_subject': 'user:1'}

    def tearDown(self):
        self.jobs.close()
        deadline = time.monotonic() + 3
        while self.jobs.sessions and time.monotonic() < deadline: time.sleep(.01)
        self.patch.stop(); self.hub.close(); self.temp.cleanup()

    def wait(self, identifier):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if identifier not in self.jobs.sessions: return self.jobs.jobs[identifier]
            time.sleep(.01)
        self.fail('worker did not finish')

    def test_deferred_local_ai_request_persists_without_source_or_model(self):
        FakeHost.local_ready = False
        result = self.jobs.start({}, self.did, 'summary', defer_if_unavailable=True)
        self.assertEqual(result['status'], 'deferred')
        self.assertFalse(self.jobs.sessions)
        self.assertIsNone(FakeHost.last.job_id)
        self.assertEqual(self.hub.app.store.list_analyses(self.did)['items'], [])
        raw = self.jobs.path.read_text()
        for text in ('秘密の合成本文', '合成分析結果', 'access_token', 'Authorization'):
            self.assertNotIn(text, raw)
        self.assertEqual(self.jobs.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(self.jobs.list(self.identity)['items']), 1)
        self.assertEqual(self.jobs.list({'subject': '2'})['items'], [])
        same = self.jobs.start({}, self.did, 'summary', defer_if_unavailable=True)
        self.assertEqual(same['id'], result['id'])
        restart = AnalysisJobs(self.jobs.client, self.temp.name)
        self.assertEqual(restart.jobs[result['id']]['status'], 'deferred')
        self.assertFalse(restart.sessions)
        self.assertIsNone(FakeHost.last.job_id)
        restart.close()

    def test_deferred_ai_is_not_automatically_retried_and_resume_is_manual(self):
        FakeHost.defer_raise_503 = True
        old = self.jobs.start({}, self.did, 'claims', defer_if_unavailable=True)
        self.assertEqual(old['status'], 'deferred')
        again = self.jobs.start({}, self.did, 'claims', old['id'], defer_if_unavailable=True)
        self.assertEqual(again['id'], old['id'])
        self.assertEqual(len(self.jobs.jobs), 1)
        self.assertIsNone(FakeHost.last.job_id)
        FakeHost.defer_raise_503 = False
        ready = self.jobs.start({}, self.did, 'claims', old['id'], defer_if_unavailable=True)
        self.assertNotEqual(ready['id'], old['id'])
        self.assertEqual(self.wait(ready['id'])['status'], 'succeeded')
        self.assertEqual(self.jobs.jobs[old['id']]['status'], 'resumed')
        self.assertEqual(self.jobs.jobs[old['id']]['resumed_as'], ready['id'])
        with self.assertRaises(AddonError):
            self.jobs.start({}, self.did, 'claims', old['id'], defer_if_unavailable=True)
        self.assertEqual(len(self.hub.app.store.list_analyses(self.did)['items']), 1)

    def test_deferred_ai_requires_explicit_opt_in_and_valid_owner(self):
        FakeHost.local_ready = False
        with self.assertRaises(AddonError) as error:
            self.jobs.start({}, self.did, 'summary')
        self.assertEqual(error.exception.status, 503)
        self.assertFalse(self.jobs.path.exists())
        with self.assertRaises(AddonError) as invalid:
            self.jobs.start({}, self.did, 'summary', defer_if_unavailable='true')
        self.assertEqual(invalid.exception.status, 400)
        fake = self.jobs.start({}, self.did, 'summary', defer_if_unavailable=True)
        with self.assertRaises(AddonError):
            self.jobs.forget(fake['id'], {'subject': '2'})
        with self.assertRaises(AddonError):
            self.jobs.start({}, self.did, 'summary', 'invalid', defer_if_unavailable=True)
        self.assertTrue(self.jobs.forget(fake['id'], self.identity)['removed'])
        self.assertEqual(self.jobs.list(self.identity)['items'], [])

    def test_result_is_saved_on_server_and_only_metadata_is_local(self):
        result = self.jobs.start({}, self.did, 'summary')
        state = self.wait(result['id']); self.assertEqual(state['status'], 'succeeded')
        stored = self.hub.app.store.list_analyses(self.did)['items']
        self.assertEqual(len(stored), 1); self.assertEqual(stored[0]['content'], '合成分析結果です。')
        local = self.jobs.path.read_text()
        for private in ('秘密の合成本文', '合成分析結果です。', 'access_token', 'Authorization'):
            self.assertNotIn(private, local)
        self.assertEqual(self.jobs.path.stat().st_mode & 0o777, 0o600)
        self.assertFalse((Path(self.temp.name) / 'library.sqlite3').exists())
        self.assertEqual(self.jobs.list({'subject': '2'})['items'], [])
        with self.assertRaises(AddonError): self.jobs.forget(result['id'], {'subject': '2'})
        self.assertTrue(self.jobs.forget(result['id'], self.identity)['removed'])
        self.assertEqual(self.jobs.list(self.identity)['items'], [])
        self.assertEqual(len(self.hub.app.store.list_analyses(self.did)['items']), 1)

    def test_cancel_aborts_inference_does_not_save_and_keeps_owner_boundary(self):
        FakeHost.gate = threading.Event()
        result = self.jobs.start({}, self.did, 'claims')
        self.assertTrue(FakeHost.last.entered.wait(2))
        with self.assertRaises(AddonError): self.jobs.cancel(result['id'], {'subject': '2'})
        with self.assertRaises(AddonError): self.jobs.start({}, self.did, 'summary')
        self.jobs.cancel(result['id'], self.identity)
        state = self.wait(result['id']); self.assertEqual(state['status'], 'canceled')
        self.assertEqual(self.hub.app.store.list_analyses(self.did)['items'], [])
        FakeHost.gate = None
        again = self.jobs.start({}, self.did, 'claims', result['id'])
        self.assertEqual(self.wait(again['id'])['status'], 'succeeded')

    def test_host_cancel_or_source_change_prevents_result_save(self):
        FakeHost.cancel_on_control = True
        result = self.jobs.start({}, self.did, 'summary'); self.assertEqual(self.wait(result['id'])['status'], 'canceled')
        FakeHost.cancel_on_control = False;FakeHost.gate = threading.Event()
        result = self.jobs.start({}, self.did, 'summary');self.assertTrue(FakeHost.last.entered.wait(2))
        self.hub.app.store.add_documents('synthetic-analysis', [{'id': 'example', 'body': '改訂本文'}])
        FakeHost.gate.set()
        self.assertEqual(self.wait(result['id'])['status'], 'failed')
        self.assertEqual(self.hub.app.store.list_analyses(self.did)['items'], [])

    def test_restart_marks_inflight_interrupted_without_persisting_credentials(self):
        FakeHost.gate = threading.Event()
        result = self.jobs.start({}, self.did, 'summary');self.assertTrue(FakeHost.last.entered.wait(2))
        restart = AnalysisJobs(self.jobs.client, self.temp.name)
        self.assertEqual(restart.jobs[result['id']]['status'], 'interrupted')
        self.assertFalse(restart.sessions)
        self.jobs.cancel(result['id'], self.identity);self.wait(result['id'])

    def test_terminal_network_failure_preserves_result_and_marks_pending(self):
        FakeHost.fail_terminal = True
        result = self.jobs.start({}, self.did, 'summary'); state = self.wait(result['id'])
        self.assertEqual(state['status'], 'succeeded');self.assertTrue(state['host_sync_pending'])
        self.assertEqual(len(self.hub.app.store.list_analyses(self.did)['items']), 1)
        self.assertEqual(FakeHost.last.finished[0][1], FakeHost.last.finished[1][1])
        FakeHost.fail_terminal = False
        self.assertFalse(self.jobs.reconcile({}, result['id'])['host_sync_pending'])
