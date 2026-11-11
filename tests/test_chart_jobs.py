import json
import threading
import unittest
from unittest.mock import patch

from qnaplibrary import host_vectors
from qnaplibrary.addon_client import AddonError
from qnaplibrary.addon_jobs import AnalysisJobs
from tests import test_addon_jobs as base

FakeHost = base.FakeHost

MODEL = 'a' * 64


class ChartHost(FakeHost):
    def __init__(self, client, headers):
        super().__init__(client, headers)
        self.request_id = self.lease_id = None
        self.resource_changed = lambda: None
        self.events = []
    def acquire_cpu(self):
        self.request_id = 'request'; self.resource_changed()
        self.lease_id = 'lease'; self.resource_changed(); self.events.append('acquire')
    def release_cpu(self):
        self.events.append('release'); self.request_id = self.lease_id = None
    def call(self, *args):
        return {key: dict(available=True, model_ref=MODEL, revision_kind='host_file_metadata_v1', execution_policy='local_only')
                for key in ('text.embed', 'text.rerank')}
    def retrieval(self, cap, inputs, query=None):
        value = dict(model_ref=MODEL, revision_kind='host_file_metadata_v1', execution_policy='local_only')
        if cap == 'text.embed': value.update(dimensions=2, vectors=[[1, 0] for _ in inputs])
        else: value['rankings'] = [dict(index=i, score=1-i) for i in range(len(inputs))]
        return value
    def stream(self, messages, require_provenance=False):
        assert require_provenance
        self.generation_provenance = dict(execution_policy='local_only', revision_kind='host_process_file_metadata_v1', model_ref=MODEL, runtime_ref='b'*64)
        super().stream(messages)
        rows = json.loads(messages[1]['content'])['elements']
        return json.dumps({'rows': [dict(label=r['label'], judgment='△', reason='原文に対応候補あり',
            citations=[r['sources'][0]['ref']]) for r in rows]})
    def finish(self, status, result=None):
        self.events.append('finish')
        return super().finish(status, result)


class ChartJobsTests(unittest.TestCase):
    tearDown = base.AnalysisJobsTests.tearDown
    wait = base.AnalysisJobsTests.wait
    def setUp(self):
        base.AnalysisJobsTests.setUp(self)
        self.cp = patch('qnaplibrary.addon_jobs.ComputeHostSession', ChartHost); self.cp.start()
        self.addCleanup(self.cp.stop)
        self.hub.app.store.add_documents('synthetic-analysis', [
            {'id': 'example', 'body': '【請求項1】正極と、負極とを備える電池。'},
            {'id': 'reference', 'body': '電池は正極と負極とを備える。'}])
        rows = host_vectors.pending(self.hub.app.store, MODEL)['items']
        host_vectors.save(self.hub.app.store, dict(model_ref=MODEL, revision_kind='host_file_metadata_v1', dimensions=2,
                         items=[dict(r, vector=[1, 0]) for r in rows]), 'test')

    def test_chart_pipeline_and_release_before_terminal(self):
        job = self.jobs.start({}, self.did, 'chart')
        session = FakeHost.last
        state = self.wait(job['id'])
        self.assertEqual(state['status'], 'succeeded')
        self.assertFalse(state['host_sync_pending']); self.assertIsNone(state['lease_id'])
        self.assertEqual(session.events, ['acquire', 'release', 'finish'])
        chart = json.loads(self.hub.app.store.list_analyses(self.did)['items'][0]['content'])
        self.assertEqual(chart['retrieval']['stages'], ['keyword','vector','graph','rerank'])
        self.assertTrue(all(r['embedding_model_ref'] == MODEL for r in chart['retrieval']['rows']))

    def test_chart_lost_save_response_reconciles_without_regeneration(self):
        data = self.jobs.client.data
        def lose(method, path, body=None):
            value = data(method, path, body)
            if method == 'POST' and path.endswith('/analyses'): raise AddonError(502, 'lost response')
            return value
        self.jobs.client.data = lose
        job = self.jobs.start({}, self.did, 'chart')
        self.assertEqual(self.wait(job['id'])['status'], 'succeeded')
        self.assertEqual(len(self.hub.app.store.list_analyses(self.did)['items']), 1)
        self.assertFalse(self.jobs.jobs[job['id']]['host_sync_pending'])

    def test_chart_cancel_waits_for_release_and_restart_reconciles_saved_result(self):
        FakeHost.gate = threading.Event()
        job = self.jobs.start({}, self.did, 'chart'); session = FakeHost.last
        self.assertTrue(session.entered.wait(3))
        self.assertEqual(json.loads(self.jobs.path.read_text())[0]['lease_id'], 'lease')
        self.jobs.cancel(job['id'], self.identity)
        self.assertEqual(self.wait(job['id'])['status'], 'canceled')
        self.assertEqual(session.events, ['acquire', 'release', 'finish'])
        FakeHost.gate = None
        again = self.jobs.start({}, self.did, 'chart', job['id']); self.wait(again['id'])
        value = self.jobs.jobs[again['id']]
        value.update(status='running', host_sync_pending=True, lease_id='lease', request_id='request')
        self.jobs._save()
        restarted = AnalysisJobs(self.jobs.client, self.temp.name)
        self.assertEqual(restarted.jobs[again['id']]['status'], 'interrupted')
        with self.assertRaises(AddonError): restarted.start({}, self.did, 'chart')
        result = restarted.reconcile({}, again['id'])
        self.assertEqual(result['status'], 'succeeded'); self.assertFalse(result['host_sync_pending'])
        self.assertEqual(FakeHost.last.events, ['release', 'finish'])

    def test_relation_job_recovers_lost_save_and_releases_cpu(self):
        def stream(session, messages, require_provenance=False):
            self.assertTrue(require_provenance)
            session.generation_provenance = dict(execution_policy='local_only', revision_kind='host_process_file_metadata_v1', model_ref=MODEL, runtime_ref='b'*64)
            return json.dumps({'proposals':[dict(relation='solution',concept='電池構成',confidence=0.8,quote='正極と、負極とを備える電池。')]})
        original = self.jobs.client.data
        def lose(method, path, body=None):
            value = original(method, path, body)
            if method == 'POST' and path.endswith('/analyses'):
                raise AddonError(502, 'synthetic lost response')
            return value
        self.jobs.client.data = lose
        with patch.object(ChartHost, 'stream', stream):
            job = self.jobs.start({}, self.did, 'relations')
            session = FakeHost.last
            state = self.wait(job['id'])
        self.assertEqual(state['status'], 'succeeded')
        self.assertFalse(state['host_sync_pending'])
        self.assertEqual(session.events, ['acquire', 'release', 'finish'])
        saved = self.hub.app.store.list_analyses(self.did)['items']
        self.assertEqual(len(saved), 1); self.assertEqual(saved[0]['kind'], 'relations')
        self.assertEqual(self.hub.app.store.one('SELECT COUNT(*) FROM graph_edges')[0], 0)
