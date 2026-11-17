"""K1d: real SQLite persistence through the existing bounded AnalysisJobs flow."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from qnaplibrary.addon_client import AddonError
from qnaplibrary.addon_jobs import AnalysisJobs
from qnaplibrary.knowledge_store import save as save_knowledge
from qnaplibrary.store import Store

BODY = '温度上昇でファンを加速する。低下では緩やかに減速する。'
QUOTE = '低下では緩やかに減速する。'
PROOF = {
    'execution_policy': 'local_only',
    'revision_kind': 'host_process_file_metadata_v1',
    'model_ref': 'a' * 64, 'runtime_ref': 'b' * 64,
}
ITEM = {
    'kind': 'principle', 'statement': '温度の増減で制御速度を変える',
    'evidence': {'quote': QUOTE}, 'conditions': [], 'limitations': [],
}


class FakeClient:
    def __init__(self, store, doc_id):
        self.store, self.doc_id = store, doc_id
        self.calls = []
        self.can_write = True
        self.change_before_save = False

    def knowledge_write_ready(self):
        return self.can_write

    def data(self, method, path, body=None):
        self.calls.append((method, path))
        if method == 'GET' and path == '/api/v1/documents/%d' % self.doc_id:
            return self.store.get_document(self.doc_id)
        if method == 'POST' and path == '/api/v1/documents/%d/knowledge-proposals' % self.doc_id:
            if self.change_before_save:
                self.store.add_documents('sample', [{'id': 'demo', 'body': '更新された文献'}])
            return save_knowledge(self.store, self.doc_id, body, actor='knowledge-job-test')
        raise AssertionError('unexpected request: ' + path)


class FakeHost:
    last = None
    count = 0
    proof_enabled = True
    raw = None
    started = None

    def __init__(self, client, headers):
        self.owner = 'user:1'
        self.job_id = None
        self.aborted = threading.Event()
        self.generation_provenance = None
        self.calls = []
        FakeHost.last = self

    def local_available(self):
        return True

    def provenance_available(self):
        return type(self).proof_enabled

    def create_job(self):
        type(self).count += 1
        self.job_id = 'kjob-' + str(type(self).count)
        return self.job_id

    def progress(self, *args):
        pass

    def heartbeat(self):
        return {'host_job_id': self.job_id, 'status': 'running',
                'cancel_requested': self.aborted.is_set()}

    def stream(self, messages, require_provenance=False):
        self.calls.append(('stream', require_provenance))
        if type(self).started:
            type(self).started.set()
            self.aborted.wait(1.5)
            if self.aborted.is_set():
                raise AddonError(409, 'canceled')
        self.generation_provenance = dict(PROOF)
        self.assert_source = messages[1]['content']
        return (type(self).raw if type(self).raw is not None else
                json.dumps({'items': [ITEM]}, ensure_ascii=False))

    def abort(self):
        self.aborted.set()

    def finish(self, status, result=None):
        self.calls.append(('finish', status))
        return {'terminal_matches': True}


class KnowledgeJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(str(Path(self.tmp.name) / 'data.sqlite'))
        self.addCleanup(self.store.close)
        self.store.create_collection('sample')
        self.store.add_documents('sample', [{'id': 'demo', 'body': BODY}])
        self.doc_id = self.store.list_documents('sample')['items'][0]['id']
        self.client = FakeClient(self.store, self.doc_id)
        FakeHost.raw = None
        FakeHost.proof_enabled = True
        FakeHost.started = None
        patch = mock.patch('qnaplibrary.addon_jobs.HostSession', FakeHost)
        patch.start()
        self.addCleanup(patch.stop)
        self.jobs = AnalysisJobs(self.client, self.tmp.name)
        self.addCleanup(self.jobs.close)

    def wait(self, job_id):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if job_id not in self.jobs.sessions:
                return self.jobs.jobs[job_id]
            time.sleep(.01)
        self.fail('job did not terminate')

    def test_verified_generation_saves_only_unreviewed_knowledge(self):
        job = self.jobs.start({}, self.doc_id, 'knowledge')
        result = self.wait(job['id'])
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertEqual(len([x for x in self.client.calls if x[0] == 'POST']), 1)
        self.assertTrue(self.client.calls[-1][1].endswith('/knowledge-proposals'))
        self.assertIn(('stream', True), FakeHost.last.calls)
        row = self.store.one("SELECT content FROM document_analyses WHERE kind='knowledge'")
        self.assertIsNotNone(row)
        proposal = json.loads(row['content'])
        self.assertEqual(proposal['generation'], PROOF)
        self.assertEqual(proposal['items'][0]['basis'], 'model_inference')
        self.assertEqual(proposal['items'][0]['review_status'], 'unreviewed')
        self.assertNotIn(BODY, self.jobs.path.read_text())

    def test_old_host_or_missing_credential_stops_before_document_read(self):
        FakeHost.proof_enabled = False
        with self.assertRaises(AddonError) as caught:
            self.jobs.start({}, self.doc_id, 'knowledge')
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.client.calls, [])
        FakeHost.proof_enabled = True
        self.client.can_write = False
        with self.assertRaises(AddonError) as caught:
            self.jobs.start({}, self.doc_id, 'knowledge')
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(self.client.calls, [])

    def test_fabricated_quote_is_not_persisted(self):
        bad = dict(ITEM, evidence={'quote': '存在しない原文'})
        FakeHost.raw = json.dumps({'items': [bad]}, ensure_ascii=False)
        job = self.jobs.start({}, self.doc_id, 'knowledge')
        result = self.wait(job['id'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.store.one(
            "SELECT COUNT(*) FROM document_analyses WHERE kind='knowledge'")[0], 0)
        self.assertNotIn(('POST', '/api/v1/documents/%d/knowledge-proposals' % self.doc_id),
                         self.client.calls)

    def test_revision_changes_at_write_boundary(self):
        self.client.change_before_save = True
        job = self.jobs.start({}, self.doc_id, 'knowledge')
        result = self.wait(job['id'])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.store.one(
            "SELECT COUNT(*) FROM document_analyses WHERE kind='knowledge'")[0], 0)

    def test_cancel_blocks_save_and_scope_does_not_leak(self):
        FakeHost.started = threading.Event()
        job = self.jobs.start({}, self.doc_id, 'knowledge')
        self.assertTrue(FakeHost.started.wait(2))
        self.jobs.cancel(job['id'], {'subject': '1'})
        result = self.wait(job['id'])
        self.assertEqual(result['status'], 'canceled')
        self.assertEqual(self.store.one(
            "SELECT COUNT(*) FROM document_analyses WHERE kind='knowledge'")[0], 0)
        self.assertNotIn(BODY, self.jobs.path.read_text())

    def test_no_other_kind_gained_knowledge_privileges(self):
        self.client.can_write = False
        # This is still a valid legacy job kind and does not probe knowledge scope.
        # The legacy FakeHost implements stream() with an optional keyword.
        with self.assertRaises(AddonError):
            self.jobs.start({}, self.doc_id, 'not-a-kind')


if __name__ == '__main__':
    unittest.main()
