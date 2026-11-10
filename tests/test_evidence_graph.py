import copy
import unittest
from qnaplibrary import evidence_graph as graph
from qnaplibrary.store import StoreError
from tests.helpers import LiveServer, Client


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.server = LiveServer(); self.addCleanup(self.server.close)
        self.client = Client(self.server.base); self.client.login_setup()
        self.store = self.server.app.store
        self.client.call('POST', '/api/v1/collections', {'name':'graph'})
        self.client.call('POST', '/api/v1/collections/graph/documents', {'documents':[
            {'id':'A','body':'正極と負極の間に固体電解質がある。'}, {'id':'B','body':'対比文献。'}]})
        docs = self.store.q('SELECT id FROM documents ORDER BY id'); self.a, self.b = [r['id'] for r in docs]
        doc = self.store.get_document(self.a)
        self.edge = {'id':'edge-1', 'source':{'kind':'document','key':str(self.a),'label':'A'},
                     'target':{'kind':'document','key':str(self.b),'label':'B'},
                     'relation':'citation','basis':'factual','confidence':1,
                     'evidence':{'doc_id':self.a,'revision':doc['revision'],'start':0,'end':2,'quote':'正極',
                                 'retrieved_at':'2026-11-11T00:00:00Z','method':'manual'}}

    def test_exact_evidence_idempotency_atomicity_and_stale(self):
        result = graph.save(self.store,self.edge,'admin')
        changes = self.store.db.total_changes
        self.assertEqual(graph.save(self.store,self.edge,'admin')['id'],result['id'])
        self.assertEqual(changes,self.store.db.total_changes)
        graph.review(self.store,'edge-1','approved','admin')
        self.assertEqual(len(graph.expand(self.store,[result['source_node']])['edges']),1)
        invalid=copy.deepcopy(self.edge);invalid['id']='bad';invalid['evidence']['quote']='偽造'
        with self.assertRaises(StoreError):graph.save(self.store,invalid,'admin')
        invalid=copy.deepcopy(self.edge);invalid['id']='bad';invalid['target']=invalid['source']
        with self.assertRaises(StoreError):graph.save(self.store,invalid,'admin')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM graph_edges')[0],1)
        self.client.call('POST','/api/v1/collections/graph/documents',{'documents':[{'id':'A','body':'更新済み'}]})
        stale=self.store.one('SELECT * FROM graph_edges')
        self.assertEqual((stale['stale'],stale['review_status']),(1,'unreviewed'))
        self.assertEqual(graph.expand(self.store,[result['source_node']])['edges'],[])
        with self.assertRaises(StoreError):graph.review(self.store,'edge-1','approved','admin')
        # Reverting the document must not restore an obsolete approval.
        self.client.call('POST','/api/v1/collections/graph/documents',{'documents':[{'id':'A','body':'正極と負極の間に固体電解質がある。'}]})
        with self.assertRaises(StoreError):graph.save(self.store,self.edge,'admin')

    def test_inferred_never_promoted_and_bounded_cycles(self):
        a=graph.save(self.store,self.edge,'admin'); graph.review(self.store,'edge-1','approved','admin')
        edge=copy.deepcopy(self.edge);edge.update(id='reverse',source=self.edge['target'],target=self.edge['source'])
        graph.save(self.store,edge,'admin');graph.review(self.store,'reverse','approved','admin')
        inferred=copy.deepcopy(self.edge);inferred.update(id='guess',relation='effect',basis='inferred',model='local-model/version1')
        inferred['target']={'kind':'concept','key':'effect-1','label':'低抵抗'}
        g=graph.save(self.store,inferred,'admin');graph.review(self.store,'guess','approved','admin')
        result=graph.expand(self.store,[a['source_node']],hops=2)
        self.assertEqual(len(result['nodes']),2);self.assertEqual(len(result['edges']),2)
        result=graph.expand(self.store,[a['source_node']],hops=2,include_inferred=True,max_nodes=2)
        self.assertTrue(result['truncated']);self.assertEqual(len(result['nodes']),2)
        result=graph.expand(self.store,[a['source_node']],include_inferred=True,max_edges=1)
        self.assertTrue(result['truncated']);self.assertEqual(len(result['edges']),1)
        self.assertEqual(self.store.one('SELECT basis FROM graph_edges WHERE id=?',(g['id'],))[0],'inferred')
        before=self.store.db.total_changes
        graph.expand(self.store,[a['source_node']],hops=2,include_inferred=True)
        self.assertEqual(self.store.db.total_changes,before)
        plan=self.store.q("EXPLAIN QUERY PLAN SELECT * FROM graph_edges WHERE source_node=? AND stale=0 AND review_status='approved' AND basis='factual' ORDER BY id LIMIT 5",(a['source_node'],))
        self.assertTrue(any('graph_edges_source' in str(tuple(row)) for row in plan))

    def test_auth_review_and_public_boundary(self):
        path='/api/v1/graph/edges'
        outsider=Client(self.server.base)
        self.assertEqual(outsider.call('POST',path,self.edge)[0],401)
        status,saved=self.client.call('POST',path,self.edge);self.assertEqual(status,200,saved)
        self.assertEqual(self.client.call('POST',path+'/edge-1/review',{'status':'approved'})[0],200)
        for scope in ('published','ro','analysis','pdf_analysis','rw'):
            token=self.server.app.auth.create_device('test-'+scope,scope)['token'];client=Client(self.server.base);client.token=token
            self.assertEqual(client.call('POST',path,self.edge)[0],403)
            self.assertEqual(client.call('POST',path+'/edge-1/review',{'status':'approved'})[0],403)
            self.assertEqual(client.call('GET',path+'/edge-1')[0],403 if scope=='published' else 200)
        self.assertEqual(self.client.call('GET','/api/v1/graph/expand?seeds='+str(saved['source_node'])+'&hops=3')[0],400)
        self.assertEqual(self.client.call('GET','/api/v1/graph/expand?seeds='+str(saved['source_node']))[0],200)

    def test_delete_and_transaction_rollback(self):
        saved=graph.save(self.store,self.edge,'admin')
        with self.assertRaises(RuntimeError):
            with self.store.tx() as db:
                db.execute('UPDATE documents SET source=? WHERE id=?',('changed',self.a))
                raise RuntimeError('rollback')
        self.assertEqual(self.store.one('SELECT stale FROM graph_edges')[0],0)
        with self.store.tx() as db:db.execute('DELETE FROM documents WHERE id=?',(self.b,))
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM graph_edges')[0],0)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM graph_nodes WHERE doc_id=?',(self.b,))[0],0)
        self.assertEqual(graph.expand(self.store,[saved['source_node']])['edges'],[])

    def test_snapshot_restore_and_strict_validation(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        from qnaplibrary.store import Store
        a=graph.save(self.store,self.edge,'admin');graph.review(self.store,'edge-1','approved','admin')
        for bad in (True, float('nan'), -0.1, 1.1):
            value=copy.deepcopy(self.edge);value.update(id='bad',confidence=bad)
            with self.assertRaises(StoreError):graph.save(self.store,value,'admin')
        value=copy.deepcopy(self.edge);value.update(id='new-node')
        value['source']={'kind':'concept','key':'rollback','label':'rollback'}
        value['target']['key']='999999'
        with self.assertRaises(StoreError):graph.save(self.store,value,'admin')
        self.assertIsNone(self.store.one("SELECT id FROM graph_nodes WHERE node_key='rollback'"))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'snapshot.sqlite3'
            with sqlite3.connect(path) as backup:self.store.db.backup(backup)
            restored=Store(path)
            try:
                self.assertEqual(restored.one('PRAGMA quick_check')[0],'ok')
                self.assertEqual(graph.expand(restored,[a['source_node']]),graph.expand(self.store,[a['source_node']]))
            finally:restored.close()
