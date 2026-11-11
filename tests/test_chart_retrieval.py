import tempfile
import threading
import unittest
from unittest.mock import Mock
from qnaplibrary import host_vectors, evidence_graph
from qnaplibrary.addon_client import AddonError
from qnaplibrary.chart_retrieval import ChartRetrieval
from tests.helpers import LiveServer, Client

MODEL = 'a' * 64


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.hub = LiveServer(); self.addCleanup(self.hub.close)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.admin = Client(self.hub.base); self.admin.login_setup()
        self.admin.call('POST', '/api/v1/collections', {'name': 'retrieval'})
        self.admin.call('POST', '/api/v1/collections/retrieval/documents', {'documents': [
            {'id': 'one', 'body': '電池は正極と負極を備える。'}, {'id': 'two', 'body': '関連する構造についての別資料。'}]})
        self.store = self.hub.app.store
        self.rows = host_vectors.pending(self.store, MODEL)['items']
        self.client = Mock(); self.paths = []
        def data(method, path, body=None):
            self.paths.append(path)
            status, value = self.admin.call(method, path, body)
            if status != 200: raise AddonError(status, str(value))
            return value
        self.client.data.side_effect = data
        self.client.settings.return_value = {'server_url': self.hub.base}
        self.host = Mock(); self.host.aborted = threading.Event()
        self.host.call.return_value = {key: dict(available=True, model_ref=MODEL, revision_kind='host_file_metadata_v1', execution_policy='local_only')
                                       for key in ('text.embed', 'text.rerank')}
        def inference(cap, inputs, query=None):
            value = dict(model_ref=MODEL, execution_policy='local_only', revision_kind='host_file_metadata_v1')
            if cap == 'text.embed': value.update(dimensions=2, vectors=[[1, 0] for _ in inputs])
            else: value['rankings'] = [dict(index=i, score=float(i)) for i in range(len(inputs))]
            return value
        self.host.retrieval.side_effect = inference
        self.index()

    def index(self):
        rows = host_vectors.pending(self.store, MODEL)['items']
        if rows: host_vectors.save(self.store, dict(model_ref=MODEL, revision_kind='host_file_metadata_v1', dimensions=2,
                         items=[dict(r, vector=[1, 0]) for r in rows]), 'test')

    def test_pipeline_cites_exact_ranges_and_reranks_graph_candidate(self):
        doc = self.store.get_document(self.rows[1]['doc_id'])
        edge = dict(id='reference', source=dict(kind='document', key=str(self.rows[0]['doc_id']), label='one'),
                    target=dict(kind='document', key=str(doc['id']), label='two'), relation='citation', basis='factual', confidence=1,
                    evidence=dict(doc_id=doc['id'], revision=doc['revision'], start=0, end=4, quote=doc['body'][:4],
                                  retrieved_at='2026-11-11T00:00:00Z', method='manual'))
        evidence_graph.save(self.store, edge, 'test'); evidence_graph.review(self.store, 'reference', 'approved', 'test')
        retriever = ChartRetrieval(self.client, self.host, self.temp.name)
        rows, trace = retriever.retrieve('電池構造', '電池', 999, 'A')
        self.assertEqual(rows[0]['via'], 'graph:reference')
        self.assertEqual([r['ref'] for r in rows], ['A-E1', 'A-E2', 'A-E3'])
        self.assertEqual(trace['stages'], ['keyword', 'vector', 'graph', 'rerank'])
        self.assertFalse(trace['vector_truncated'])
        for row in rows:
            self.assertEqual(self.store.get_document(row['doc_id'])['body'][row['start']:row['end']], row['quote'])
        retriever.finish()
        self.assertNotIn('/api/v1/documents/%d' % doc['id'], self.paths)

    def test_incomplete_index_and_mid_search_source_change_fail_closed(self):
        retriever = ChartRetrieval(self.client, self.host, self.temp.name)
        self.admin.call('POST', '/api/v1/collections/retrieval/documents', {'documents': [{'id': 'one', 'body': '電池が変更された。'}]})
        with self.assertRaises(AddonError): retriever.finish()
        with self.assertRaises(AddonError): ChartRetrieval(self.client, self.host, self.temp.name)
        self.index()
        with self.assertRaises(AddonError): retriever.finish()

    def test_read_bounds_no_write_and_published_scope_rejection(self):
        cid = self.rows[0]['chunk_id']; did = self.rows[0]['doc_id']; rev = self.rows[0]['revision']
        paths = ['/api/v1/chunks/%d/evidence' % cid,
                 '/api/v1/documents/%d/evidence?start=0&end=2&revision=%s' % (did, rev)]
        before = self.store.db.total_changes
        for path in paths: self.assertEqual(self.admin.call('GET', path)[0], 200)
        self.assertEqual(self.store.db.total_changes, before)
        for end in (0, 651, 2**64):
            self.assertEqual(self.admin.call('GET', '/api/v1/documents/%d/evidence?start=0&end=%d&revision=%s' % (did, end, rev))[0], 400)
        public = Client(self.hub.base); public.token = self.hub.app.auth.create_device('public', 'published')['token']
        for path in paths: self.assertEqual(public.call('GET', path)[0], 403)
        with self.store.tx() as db: db.execute('UPDATE chunks SET text=? WHERE id=?', ('本文にはない断片', cid))
        self.assertFalse(self.admin.call('GET', paths[0])[1]['citable'])

    def test_cache_retains_only_two_completed_snapshots(self):
        for n in range(4):
            self.admin.call('POST', '/api/v1/collections/retrieval/documents', {'documents': [{'id': 'one', 'body': '電池%d' % n}]})
            self.index()
            retriever = ChartRetrieval(self.client, self.host, self.temp.name)
        self.assertEqual(len(list(retriever.cache.root.glob('*.sqlite3'))), 2)

    def test_model_swap_and_cancellation_never_fall_back(self):
        retriever = ChartRetrieval(self.client, self.host, self.temp.name)
        inference = self.host.retrieval.side_effect
        self.host.retrieval.side_effect = lambda *a: dict(inference(*a), model_ref='b' * 64)
        with self.assertRaises(AddonError): retriever.retrieve('電池', '電池', 999, 'A')
        self.assertEqual(self.host.retrieval.call_count, 1)
        self.host.retrieval.reset_mock(); self.host.aborted.set()
        with self.assertRaises(AddonError): retriever.retrieve('電池', '電池', 999, 'A')
        self.host.retrieval.assert_not_called()
