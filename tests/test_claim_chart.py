import copy
import json
import threading
import unittest
from unittest.mock import patch
from qnaplibrary import claim_chart as chart
from qnaplibrary.store import StoreError
from qnaplibrary.chart_storage import review
from tests.helpers import LiveServer, Client

BODY='【請求項1】正極と、負極とを備える電池。\n【請求項2】固体電解質を有する請求項1の電池。\n【発明の詳細な説明】混入してはいけない説明'


class ChartTests(unittest.TestCase):
    def setUp(self):
        self.server=LiveServer();self.addCleanup(self.server.close)
        self.client=Client(self.server.base);self.client.login_setup();self.store=self.server.app.store
        self.client.call('POST','/api/v1/collections',{'name':'charts'})
        self.client.call('POST','/api/v1/collections/charts/documents',{'documents':[
            {'id':'claim','body':BODY},{'id':'reference','body':'正極と負極が存在する電池。'}]})
        ids=[r[0] for r in self.store.q('SELECT id FROM documents ORDER BY id')]
        self.doc=self.store.get_document(ids[0]);self.ref=self.store.get_document(ids[1])
        claim,items=chart.elements(BODY,1)
        self.chart={'schema_version':1,'review_status':'unreviewed','claim_no':1,'claim_text':claim,'rows':[]}
        for element in items:
            ref=element['label']+'-E1'
            evidence={'ref':ref,'doc_id':self.ref['id'],'revision':self.ref['revision'],'start':0,'end':2,'quote':'正極','via':'keyword','rerank_score':1.0}
            self.chart['rows'].append({'element':element,'evidence':[evidence],
                'assessment':{'label':element['label'],'judgment':'△','reason':'候補の記載を確認','citations':[ref]}})

    def save(self,value=None,identifier='chart-test'):
        return self.store.save_analysis(self.doc['id'],{'id':identifier,'kind':'chart',
            'source_revision':self.doc['revision'],'content':json.dumps(value or self.chart,ensure_ascii=False)},actor='test')

    def test_atomic_rejection_missing_duplicate_cross_row_and_forgery(self):
        self.assertNotIn('混入',chart.elements(BODY,2)[0])
        cases=[]
        value=copy.deepcopy(self.chart);value['rows'].pop();cases.append(value)
        value=copy.deepcopy(self.chart);value['rows'][1]=value['rows'][0];cases.append(value)
        value=copy.deepcopy(self.chart);value['rows'][0]['assessment']['citations']=['B-E1'];cases.append(value)
        value=copy.deepcopy(self.chart);value['rows'][0]['evidence'][0]['quote']='偽造';cases.append(value)
        value=copy.deepcopy(self.chart);value['rows'][0]['assessment']['citations']=[];cases.append(value)
        for value in cases:
            with self.assertRaises(StoreError):self.save(value)
            self.assertEqual(self.store.one('SELECT COUNT(*) FROM document_analyses')[0],0)
        self.save();count=self.store.db.total_changes;self.save();self.assertEqual(count,self.store.db.total_changes)

    def test_dependency_invalidation_survives_revert_and_delete(self):
        self.save();review(self.store,'chart-test','approved','admin')
        self.assertEqual(self.store.list_analyses(self.doc['id'])['items'][0]['review_status'],'approved')
        self.client.call('POST','/api/v1/collections/charts/documents',{'documents':[{'id':'reference','body':'更新'}]})
        row=self.store.list_analyses(self.doc['id'])['items'][0]
        self.assertTrue(row['stale']);self.assertEqual(row['review_status'],'unreviewed')
        self.client.call('POST','/api/v1/collections/charts/documents',{'documents':[{'id':'reference','body':self.ref['body']}]})
        with self.assertRaises(StoreError):review(self.store,'chart-test','approved','admin')
        self.save(identifier='new-version')
        with self.store.tx() as db:db.execute('DELETE FROM documents WHERE id=?',(self.ref['id'],))
        self.assertTrue(all(row['stale'] for row in self.store.list_analyses(self.doc['id'])['items']))

    def test_generation_uses_host_and_strict_keyword_policy(self):
        outer=self
        class Data:
            def data(self,method,path,body=None):
                if path=='/api/v1/search':
                    outer.assertEqual((body['mode'],body['rerank']),('keyword',False))
                    return {'results':[{'doc_id':outer.ref['id'],'text':outer.ref['body']}]}
                if path.startswith('/api/v1/graph/documents/'):
                    return {'nodes':[]}
                return outer.ref
        class Session:
            aborted=threading.Event()
            def progress(self,*args):pass
            generation_provenance = {'execution_policy':'local_only','revision_kind':'host_process_file_metadata_v1','model_ref':'a'*64,'runtime_ref':'b'*64}
            def stream(self,messages,require_provenance=False):
                outer.assertTrue(require_provenance)
                inputs=json.loads(messages[1]['content'])['elements']
                return json.dumps({'rows':[{'label':r['label'],'judgment':'△','reason':'根拠の候補',
                    'citations':[r['sources'][0]['ref']]} for r in inputs]})
        with patch('qnaplibrary.chart_retrieval.ChartRetrieval') as factory:
            retriever = factory.return_value
            def retrieve(query, keywords, excluded, label):
                row = next(r for r in self.chart['rows'] if r['element']['label'] == label)
                return row['evidence'], self.trace()
            retriever.retrieve.side_effect = retrieve
            value=json.loads(chart.generate(Data(),Session(),self.doc,1,'/unused'))
            retriever.finish.assert_called_once()
        self.assertEqual(value['retrieval']['stages'], ['keyword','vector','graph','rerank'])
        chart.validate(value,BODY,self.store.get_document)
        self.assertTrue(all(r['evidence'] for r in value['rows']))

    def test_review_scope_and_stale_save(self):
        self.save()
        device=Client(self.server.base);device.token=self.server.app.auth.create_device('analysis','analysis')['token']
        path='/api/v1/analyses/chart-test/review'
        self.assertEqual(device.call('POST',path,{'status':'approved'})[0],403)
        self.assertEqual(self.client.call('POST',path,{'status':'approved'})[0],200)
        self.client.call('POST','/api/v1/collections/charts/documents',{'documents':[{'id':'reference','body':'変更'}]})
        with self.assertRaises(StoreError):self.save(identifier='stale-input')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM document_analyses')[0],1)

    def test_receipt_is_private_bounded_metadata_and_read_only(self):
        self.save()
        path = '/api/v1/analyses/chart-test/receipt'
        before = self.store.db.total_changes
        status, value = self.client.call('GET', path)
        self.assertEqual(status, 200)
        self.assertTrue(value['found'])
        self.assertEqual(set(value['analysis']), {'id', 'doc_id', 'kind', 'source_revision'})
        self.assertEqual(self.store.db.total_changes, before)
        self.assertFalse(self.client.call('GET', '/api/v1/analyses/missing/receipt')[1]['found'])
        stranger = Client(self.server.base)
        self.assertEqual(stranger.call('GET', path)[0], 401)
        stranger.token = self.server.app.auth.create_device('public-receipt', 'published')['token']
        self.assertEqual(stranger.call('GET', path)[0], 403)


    def test_generation_provenance_storage_is_atomic_and_legacy_compatible(self):
        value = copy.deepcopy(self.chart)
        value['schema_version'] = 2
        value['retrieval'] = self.retrieval(value)
        proof = {'execution_policy': 'local_only', 'revision_kind': 'host_process_file_metadata_v1',
                 'model_ref': 'a'*64, 'runtime_ref': 'b'*64}
        for generation in (None, {'executed': False, 'reason': 'no_evidence'},
                           {'executed': True, 'provenance': dict(proof, runtime_ref='invalid')},
                           {'executed': 1, 'provenance': proof}):
            value['generation'] = generation
            with self.assertRaises(StoreError): self.save(value)
            self.assertEqual(self.store.one('SELECT COUNT(*) FROM document_analyses')[0], 0)
        value['generation'] = {'executed': True, 'provenance': proof}
        self.save(value)
        self.save(identifier='legacy')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM document_analyses')[0], 2)

    def test_no_evidence_never_calls_llm_or_claims_provenance(self):
        from unittest.mock import Mock
        session = Mock()
        session.aborted = threading.Event()
        with patch('qnaplibrary.chart_retrieval.ChartRetrieval') as factory:
            factory.return_value.retrieve.return_value = ([], dict(self.trace(),candidate_count=0))
            value = json.loads(chart.generate(Mock(), session, self.doc, 1, '/unused'))
        session.stream.assert_not_called()
        self.assertEqual(value['generation'], {'executed': False, 'reason': 'no_evidence'})
        self.save(value)
        value['generation']['provenance'] = {}
        with self.assertRaises(StoreError): self.save(value, identifier='forged')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM document_analyses')[0], 1)


    def trace(self):
        return dict(stages=['keyword','vector','graph','rerank'], embedding_model_ref='a'*64,
                    reranker_model_ref='b'*64,revision_kind='host_file_metadata_v1',snapshot_etag='c'*32+':1',
                    vector_scanned=1,vector_total=1,vector_truncated=False,graph_truncated=False,candidate_count=1)

    def retrieval(self, value):
        return dict(stages=['keyword','vector','graph','rerank'],graph_truncated=False,vector_truncated=False,
                    rows=[dict(self.trace(),label=r['element']['label']) for r in value['rows']])

    def test_retrieval_trace_rejects_mismatch_without_partial_write(self):
        value=copy.deepcopy(self.chart);value['schema_version']=2;value['retrieval']=self.retrieval(value)
        value['generation']=dict(executed=True,provenance=dict(execution_policy='local_only',
            revision_kind='host_process_file_metadata_v1',model_ref='a'*64,runtime_ref='b'*64))
        invalid=[]
        for field,new in [('label','wrong'),('embedding_model_ref','invalid'),('vector_scanned',True),
                          ('vector_total',0),('candidate_count',13),('snapshot_etag','secret'),('graph_truncated',1)]:
            v=copy.deepcopy(value);v['retrieval']['rows'][0][field]=new;invalid.append(v)
        v=copy.deepcopy(value);v['retrieval']['rows'][0]['embedding_model_ref']='d'*64;invalid.append(v)
        v=copy.deepcopy(value);v['retrieval']['graph_truncated']=True;invalid.append(v)
        for field,new in [('via','unknown'),('rerank_score',float('nan'))]:
            v=copy.deepcopy(value);v['rows'][0]['evidence'][0][field]=new;invalid.append(v)
        for v in invalid:
            with self.assertRaises(StoreError):self.save(v)
            self.assertEqual(self.store.one('SELECT COUNT(*) FROM document_analyses')[0],0)
        self.save(value)
