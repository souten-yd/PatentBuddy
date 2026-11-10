import copy
import unittest
from qnaplibrary import host_vectors as vectors
from qnaplibrary.store import StoreError
from tests.helpers import LiveServer,Client


class VectorTests(unittest.TestCase):
    def setUp(self):
        self.hub=LiveServer();self.addCleanup(self.hub.close);self.store=self.hub.app.store
        self.admin=Client(self.hub.base);self.admin.login_setup()
        self.admin.call('POST','/api/v1/collections',{'name':'vector-tests'})
        self.admin.call('POST','/api/v1/collections/vector-tests/documents',{'documents':[{'id':'one','body':'正極と負極の電池。'},{'id':'two','body':'固体電解質層。'}]})
        self.pending=vectors.pending(self.store,'a'*64)
        self.body={'model_ref':'a'*64,'revision_kind':'host_file_metadata_v1','dimensions':2,
                   'items':[dict(row,vector=[1,0]) for row in self.pending['items']]}

    def test_atomic_revision_check_and_identical_no_write(self):
        value=copy.deepcopy(self.body);value['items'][-1]['chunk_sha256']='b'*64
        with self.assertRaises(StoreError):vectors.save(self.store,value,'test')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM host_vectors')[0],0)
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM host_vector_spaces')[0],0)
        self.assertEqual(vectors.save(self.store,self.body,'test')['stored'],2)
        before=self.store.db.total_changes
        self.assertEqual(vectors.save(self.store,self.body,'test')['unchanged'],2)
        self.assertEqual(self.store.db.total_changes,before)
        self.assertEqual(vectors.pending(self.store,'a'*64)['items'],[])
        self.admin.call('POST','/api/v1/collections/vector-tests/documents',{'documents':[{'id':'one','body':'変更された電池。'}]})
        with self.assertRaises(StoreError):vectors.save(self.store,self.body,'test')
        self.assertEqual(len(vectors.pending(self.store,'a'*64)['items']),1)

    def test_float_limits_model_spaces_and_pagination(self):
        first=vectors.pending(self.store,'a'*64,limit=1)
        second=vectors.pending(self.store,'a'*64,after=first['next_cursor'],limit=1)
        self.assertNotEqual(first['items'][0]['chunk_id'],second['items'][0]['chunk_id'])
        for bad in (float('nan'),float('inf'),1e100,True):
            value=copy.deepcopy(self.body);value['items'][0]['vector']=[bad,0]
            with self.assertRaises(StoreError):vectors.save(self.store,value,'test')
        vectors.save(self.store,self.body,'test')
        value=copy.deepcopy(self.body);value['model_ref']='b'*64
        vectors.save(self.store,value,'test')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM host_vectors')[0],4)
        vectors.remove(self.store,'a'*64,'test')
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM host_vectors')[0],2)
        with self.store.tx() as db:db.execute('DELETE FROM documents WHERE id=?',(self.pending['items'][0]['doc_id'],))
        self.assertEqual(self.store.one('SELECT COUNT(*) FROM host_vectors')[0],1)

    def test_scopes_private_api_and_local_token(self):
        for scope in ('ro','pdf_analysis','analysis','published','embedding','research_analysis'):
            client=Client(self.hub.base);client.token=self.hub.app.auth.create_device(scope,scope)['token']
            status,_=client.call('POST','/api/v1/host-vectors',self.body)
            self.assertEqual(status,200 if scope in ('embedding','research_analysis') else 403)
            self.assertEqual(client.call('GET','/api/v1/host-vectors/pending?model_ref='+'a'*64)[0],403 if scope=='published' else 200)
            self.assertEqual(client.call('POST','/api/v1/collections',{'name':'forbidden'})[0],403)
            self.assertEqual(client.call('DELETE','/api/v1/host-vectors/'+'a'*64)[0],403)
        token=self.hub.app.auth.local_token('embedding')
        self.assertEqual(self.hub.app.auth.device_for_token(token,'127.0.0.1')['scopes'],'embedding')
        self.assertIsNone(self.hub.app.auth.device_for_token(token,'192.168.1.2'))
