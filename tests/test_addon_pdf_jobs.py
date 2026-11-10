import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from qnaplibrary.addon_client import AddonClient, AddonError
from qnaplibrary.addon_pdf_jobs import PDFJobs
from tests.helpers import Client, LiveServer
from tests.test_pdf_store import CONTENT, extraction


class PDFHost:
    gate = None
    fail_terminal = False
    count = 0
    def __init__(self, client, headers):
        self.owner = 'user:' + headers.get('owner', '1')
        self.aborted = threading.Event(); self.request_id = None; self.lease_id = None
    def grant(self, grant_id): return {'name': 'private-test.pdf'}
    def create_job(self, title):
        PDFHost.count += 1; self.job_id = 'pdf-test-%d' % PDFHost.count; return self.job_id
    def acquire_cpu(self): self.lease_id = 'lease'; self.request_id = 'request'
    def release_cpu(self): self.lease_id = None; self.request_id = None
    def progress(self, *args): pass
    def heartbeat(self): return {'status': 'running', 'cancel_requested': False}
    def download(self, grant_id, path): path.write_bytes(CONTENT)
    def abort(self): self.aborted.set()
    def finish(self, status, result=None):
        if self.fail_terminal: raise AddonError(502, 'unavailable')
        return {'terminal_matches': True, 'status': status}


def extract(source, cancel=None, **kwargs):
    if PDFHost.gate:
        while not PDFHost.gate.wait(.01):
            if cancel.is_set(): raise ValueError('cancel')
    return extraction()


class PDFJobTests(unittest.TestCase):
    def setUp(self):
        self.hub = LiveServer(); self.temp = tempfile.TemporaryDirectory()
        admin = Client(self.hub.base); admin.login_setup()
        config = Path(self.temp.name) / 'connection.json'
        config.write_text(json.dumps({'server_url': self.hub.base, 'server_token': self.hub.app.auth.local_token('pdf_import')})); config.chmod(0o600)
        PDFHost.gate = None; PDFHost.fail_terminal = False
        self.patches = [patch('qnaplibrary.addon_pdf_jobs.PDFHostSession', PDFHost),
                        patch('qnaplibrary.addon_pdf_jobs.extract_pdf', extract),
                        patch('qnaplibrary.addon_pdf_jobs.capabilities', return_value={'synthetic': True})]
        for p in self.patches: p.start()
        self.client = AddonClient(self.temp.name)
        self.jobs = PDFJobs(self.client, self.temp.name)
        self.identity = {'subject': '1', 'actor_subject': 'user:1'}

    def tearDown(self):
        self.jobs.close()
        for p in self.patches: p.stop()
        self.hub.close(); self.temp.cleanup()

    def wait(self, identifier):
        end = time.monotonic() + 5
        while identifier in self.jobs.sessions and time.monotonic() < end: time.sleep(.01)
        self.assertNotIn(identifier, self.jobs.sessions)
        return self.jobs.jobs[identifier]

    def test_canonical_import_and_private_scratch_cleanup(self):
        job = self.jobs.start({}, 'synthetic')
        state = self.wait(job['id'])
        self.assertEqual(state['status'], 'succeeded')
        self.assertFalse(state['host_sync_pending'])
        self.assertEqual(self.hub.app.store.one('SELECT count(*) FROM document_pdfs')[0], 1)
        self.assertEqual([p.name for p in self.jobs.work.iterdir()], ['.lock'])
        local = self.jobs.path.read_text()
        for value in (CONTENT.decode(), '電池を備える。', 'private-test.pdf', self.client.settings()['server_token']):
            self.assertNotIn(value, local)
        with self.assertRaises(AddonError): self.jobs.forget(job['id'], {'subject': '2'})
        self.jobs.forget(job['id'], self.identity)
        self.assertEqual(self.hub.app.store.one('SELECT count(*) FROM document_pdfs')[0], 1)

    def test_cancel_does_not_save_and_owner_cannot_cross(self):
        PDFHost.gate = threading.Event()
        job = self.jobs.start({}, 'synthetic')
        with self.assertRaises(AddonError): self.jobs.cancel(job['id'], {'subject': '2'})
        with self.assertRaises(AddonError): self.jobs.start({}, 'synthetic')
        self.jobs.cancel(job['id'], self.identity)
        self.assertEqual(self.wait(job['id'])['status'], 'canceled')
        self.assertEqual(self.hub.app.store.one('SELECT count(*) FROM document_pdfs')[0], 0)
        self.assertEqual([p.name for p in self.jobs.work.iterdir()], ['.lock'])

    def test_lost_save_response_recovers_receipt_without_duplicate(self):
        call = self.client.data
        def lose_response(method, path, body=None):
            result = call(method, path, body)
            if path == '/api/v1/pdf-imports': raise AddonError(502, 'lost response')
            return result
        self.client.data = lose_response
        job = self.jobs.start({}, 'synthetic')
        state = self.wait(job['id'])
        self.assertEqual(state['status'], 'succeeded')
        self.assertIsNotNone(state['doc_id'])
        self.assertFalse(state['host_sync_pending'])
        self.assertEqual(self.hub.app.store.one('SELECT count(*) FROM document_pdfs')[0], 1)

    def test_unknown_save_waits_for_reconciliation(self):
        call = self.client.data
        def unavailable(method, path, body=None):
            if path.startswith('/api/v1/pdf-imports/'):
                raise AddonError(502, 'offline')
            result = call(method, path, body)
            if path == '/api/v1/pdf-imports': raise AddonError(502, 'lost response')
            return result
        self.client.data = unavailable
        job = self.jobs.start({}, 'synthetic'); state = self.wait(job['id'])
        self.assertEqual(state['status'], 'interrupted')
        self.assertTrue(state['host_sync_pending'])
        self.client.data = call
        result = self.jobs.reconcile({}, job['id'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertFalse(result['host_sync_pending'])
        self.assertEqual(self.hub.app.store.one('SELECT count(*) FROM document_pdfs')[0], 1)

    def test_terminal_retry_and_restart_scratch_removal(self):
        PDFHost.fail_terminal = True
        job = self.jobs.start({}, 'synthetic'); state = self.wait(job['id'])
        self.assertTrue(state['host_sync_pending'])
        self.jobs.close()
        orphan = self.jobs.work / ('a' * 32); orphan.mkdir(); (orphan / 'source.pdf').write_bytes(CONTENT)
        self.jobs = PDFJobs(self.client, self.temp.name)
        self.assertFalse(orphan.exists())
        PDFHost.fail_terminal = False
        restored = self.jobs.reconcile({}, job['id'])
        self.assertEqual(restored['status'], 'succeeded')
        self.assertFalse(restored['host_sync_pending'])
        with self.assertRaises(OSError): PDFJobs(self.client, self.temp.name)


if __name__ == '__main__': unittest.main()
