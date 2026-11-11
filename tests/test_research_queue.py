import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from qnaplibrary import research_queue as queue
from qnaplibrary.store import Store, StoreError
from tests.helpers import LiveServer, Client


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.store=Store(self.directory.name+'/test.sqlite');self.addCleanup(self.store.close)
        self.value=dict(id='a'*32,query='ta=inverter',limit=10,confirm_public=True)
        self.result=dict(records=[dict(publication='EP1004359B1',language='en',family=None,title='Synthetic',sources=['epo_ops'],cells=[])],
                         provider='epo_ops',fetched=1,reported_total=5,truncated=True)

    def test_idempotency_atomic_result_and_restore(self):
        initial=queue.create(self.store,self.value,'admin');changes=self.store.db.total_changes
        self.assertEqual(queue.create(self.store,self.value,'admin'),initial)
        self.assertEqual(self.store.db.total_changes,changes)
        with self.assertRaises(StoreError):queue.create(self.store,dict(self.value,query='different'),'admin')
        job=queue.claim(self.store)
        self.assertNotIn('lease',queue.get(self.store,job['id']))
        self.assertIsNone(queue.claim(self.store))
        bad=dict(self.result,records=[{}])
        with self.assertRaises(StoreError):queue.finish(self.store,job,bad)
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0],0)
        saved=queue.finish(self.store,job,self.result)
        self.assertEqual(saved['state'],'awaiting_selection')
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0],1)
        self.assertEqual(self.store.one('SELECT count(*) FROM research_discoveries')[0],1)
        backup=sqlite3.connect(self.directory.name+'/backup.sqlite');self.store.db.backup(backup);backup.close()
        restored=Store(self.directory.name+'/backup.sqlite')
        try:
            self.assertEqual(queue.get(restored,job['id']),saved)
            self.assertEqual(restored.one('PRAGMA quick_check')[0],'ok')
        finally:restored.close()

    def test_cancel_and_expired_lease_fence_old_worker(self):
        queue.create(self.store,self.value,'admin');old=queue.claim(self.store)
        self.store.db.execute('UPDATE research_requests SET lease_until=0')
        fresh=queue.claim(self.store)
        self.assertNotEqual(old['lease'],fresh['lease'])
        with self.assertRaises(StoreError):queue.finish(self.store,old,self.result)
        canceled=queue.transition(self.store,fresh['id'],fresh['revision'],'cancel','admin')
        with self.assertRaises(StoreError):queue.finish(self.store,fresh,self.result)
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0],0)
        retry=queue.transition(self.store,fresh['id'],canceled['revision'],'retry','admin')
        self.assertEqual(retry['state'],'queued')
        self.assertEqual(len(queue.list_requests(self.store)['items']),1)
        with self.assertRaises(StoreError):queue.transition(self.store,fresh['id'],canceled['revision'],'cancel','admin')

    def test_real_api_worker_waiting_keys_and_resume(self):
        server=LiveServer();self.addCleanup(server.close)
        admin=Client(server.base);admin.login_setup();path='/api/v1/research/requests'
        self.assertEqual(Client(server.base).call('POST',path,self.value)[0],401)
        reader=Client(server.base);reader.token=server.app.auth.create_device('test','ro')['token']
        self.assertEqual(reader.call('GET',path)[0],403)
        csrf=admin.csrf;admin.csrf='wrong'
        self.assertEqual(admin.call('POST',path,self.value)[0],403);admin.csrf=csrf
        scoped=Client(server.base);scoped.token=server.app.auth.create_device('research-only','research')['token']
        self.assertEqual(scoped.call('POST',path,self.value)[0],200)
        self.assertEqual(scoped.call('GET',path)[0],200)
        for private_path in ('/api/v1/collections','/api/settings','/api/debug/bundle'):
            self.assertEqual(scoped.call('GET',private_path)[0],403)
        self.assertEqual(scoped.call('POST','/api/v1/collections',{'name':'forbidden'})[0],403)
        self.assertEqual(admin.call('POST',path,self.value)[0],200)
        self.assertTrue(server.app.research_worker.run_once())
        state=admin.call('GET',path+'/'+self.value['id'])[1]
        self.assertEqual(state['state'],'waiting_credentials')
        self.assertFalse(server.app.research_worker.run_once())
        self.assertEqual(admin.call('POST',path+'/'+self.value['id']+'/transition',{'revision':state['revision'],'action':'retry'})[0],200)
        with patch.object(server.app.config,'secret',return_value='secret'),patch('qnaplibrary.research_discovery.search',return_value=self.result):
            self.assertTrue(server.app.research_worker.run_once())
        state=admin.call('GET',path+'/'+self.value['id'])[1]
        self.assertEqual(state['state'],'awaiting_selection')
        self.assertNotIn('secret',json.dumps(state))
        self.assertNotIn('lease',state)
        self.assertEqual(admin.call('GET',path)[1]['items'][0]['id'],self.value['id'])
