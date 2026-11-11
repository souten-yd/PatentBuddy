import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import urlsplit,parse_qs
from qnaplibrary import host_vectors
from qnaplibrary.vector_cache import VectorCache
from qnaplibrary.addon_client import AddonError
from qnaplibrary.store import StoreError
from tests.helpers import LiveServer,Client


class VectorCacheTests(unittest.TestCase):
    def setUp(self):
        self.hub=LiveServer();self.addCleanup(self.hub.close);self.store=self.hub.app.store
        self.admin=Client(self.hub.base);self.admin.login_setup()
        self.admin.call('POST','/api/v1/collections',{'name':'vectors'})
        self.admin.call('POST','/api/v1/collections/vectors/documents',{'documents':[
            {'id':'one','body':'正極と電解質層の電池。'},{'id':'two','body':'植物の葉。'},{'id':'three','body':'金属。'}]})
        pending=host_vectors.pending(self.store,'a'*64)['items']
        host_vectors.save(self.store,{'model_ref':'a'*64,'revision_kind':'host_file_metadata_v1','dimensions':3,
            'items':[dict(row,vector=v) for row,v in zip(pending,[[1,0,0],[0,1,0],[0,0,1]])]},'test')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.cache=VectorCache(self.tmp.name)
        store=self.store;self.calls=[];calls=self.calls
        class Source:
            def settings(self):return {'server_url':'http://127.0.0.1:17871'}
            def data(self,method,path,body=None):
                calls.append(path);parts=urlsplit(path);query=parse_qs(parts.query)
                if parts.path.endswith('/manifest'):return host_vectors.manifest(store,'a'*64)
                return host_vectors.page(store,'a'*64,query['etag'][0],int(query['after'][0]))
        self.source=Source()

    def test_snapshot_cache_and_warm_search_no_server_vector_reads(self):
        path,state=self.cache.synchronize(self.source,'a'*64)
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.calls.clear();before=self.store.db.total_changes
        again,_=self.cache.synchronize(self.source,'a'*64)
        self.assertEqual(again,path);self.assertEqual(len(self.calls),1);self.assertTrue(self.calls[0].endswith('/manifest'))
        result=self.cache.search(path,state,[0,1,0],limit=2)
        self.assertEqual(result['results'][0]['doc_id'],2);self.assertEqual(result['scanned'],3);self.assertFalse(result['truncated'])
        self.assertEqual(self.store.db.total_changes,before)
        with sqlite3.connect(path) as db:
            columns=[r[1] for r in db.execute('PRAGMA table_info(vectors)')]
            self.assertEqual(columns,['chunk_id','doc_id','revision','vec','norm'])
        self.assertNotIn('電池'.encode(),path.read_bytes())

    def test_mutation_changes_snapshot_and_rollbacks_preserve_version(self):
        first=host_vectors.manifest(self.store,'a'*64)
        with self.assertRaises(RuntimeError):
            with self.store.tx() as db:
                db.execute('DELETE FROM host_vectors WHERE chunk_id=1');raise RuntimeError('rollback')
        self.assertEqual(host_vectors.manifest(self.store,'a'*64),first)
        with self.store.tx() as db:db.execute('DELETE FROM documents WHERE id=1')
        current=host_vectors.manifest(self.store,'a'*64)
        self.assertNotEqual(current['etag'],first['etag']);self.assertEqual(current['vector_count'],2)
        with self.assertRaises(StoreError):host_vectors.page(self.store,'a'*64,first['etag'])
        host_vectors.remove(self.store,'a'*64,'test')
        rows=host_vectors.pending(self.store,'a'*64)['items']
        host_vectors.save(self.store,{'model_ref':'a'*64,'revision_kind':'host_file_metadata_v1','dimensions':3,
            'items':[dict(row,vector=[1,0,0]) for row in rows]},'test')
        self.assertNotEqual(host_vectors.manifest(self.store,'a'*64)['epoch'],first['epoch'])

    def test_changed_snapshot_does_not_publish_partial_cache(self):
        original=self.source.data;count=[0]
        def changed(method,path,body=None):
            value=original(method,path,body)
            if '/page?' in path:
                count[0]+=1
                if count[0]==1:
                    with self.store.tx() as db:db.execute('DELETE FROM host_vectors WHERE chunk_id=1')
            return value
        self.source.data=changed
        with self.assertRaises((StoreError,AddonError)):self.cache.synchronize(self.source,'a'*64)
        self.assertEqual(list((Path(self.tmp.name)/'vector-cache').iterdir()),[])

    def test_cancel_and_time_budget_and_private_api(self):
        cancel=threading.Event();cancel.set()
        with self.assertRaises(AddonError):self.cache.synchronize(self.source,'a'*64,cancel)
        path,state=self.cache.synchronize(self.source,'a'*64)
        with self.assertRaises(AddonError):self.cache.search(path,state,[1,0,0],cancel=cancel)
        self.assertTrue(self.cache.search(path,state,[1,0,0],seconds=0)['truncated'])
        client=Client(self.hub.base);client.token=self.hub.app.auth.create_device('public','published')['token']
        self.assertEqual(client.call('GET','/api/v1/host-vectors/'+'a'*64+'/manifest')[0],403)
        client.token=self.hub.app.auth.create_device('read','ro')['token']
        self.assertEqual(client.call('GET','/api/v1/host-vectors/'+'a'*64+'/manifest')[0],200)
