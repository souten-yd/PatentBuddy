import sqlite3
import tempfile
import unittest

from qnaplibrary import research_store as research
from qnaplibrary.store import Store, StoreError
from tests.helpers import LiveServer, Client


class ResearchStoreTests(unittest.TestCase):
    def record(self):
        return dict(publication='EP1004359B1', language='en', family=None,
                    title='Synthetic private research', sources=['epo'], cells=['power'])

    def test_retry_cas_and_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory + '/db.sqlite')
            try:
                first = research.create(store, [self.record()], 'admin')
                identifier = first['snapshot']['revision']
                changes = store.db.total_changes
                self.assertEqual(research.create(store, [self.record()] * 2, 'admin'), first)
                self.assertEqual(store.db.total_changes, changes)
                value = dict(snapshot_revision=identifier, expected_revision=0,
                             masked_cells=[], pinned=[], selected=[first['snapshot']['items'][0]['id']], limit=10)
                saved = research.save_selection(store, identifier, value, 'admin')
                self.assertEqual(saved['selection_revision'], 1)
                self.assertFalse(saved['selection']['preview']['download_ready'])
                changes = store.db.total_changes
                self.assertEqual(research.save_selection(store, identifier, value, 'admin'), saved)
                self.assertEqual(store.db.total_changes, changes)
                with self.assertRaises(StoreError):
                    research.save_selection(store, identifier, dict(value, limit=1), 'admin')
                with self.assertRaises(StoreError):
                    research.save_selection(store, identifier, dict(value, snapshot_revision='old'), 'admin')
                self.assertEqual(research.get(store, identifier), saved)
                backup = sqlite3.connect(directory + '/backup.sqlite')
                with store.lock:
                    store.db.backup(backup)
                backup.close()
                restored = Store(directory + '/backup.sqlite')
                try:
                    self.assertEqual(research.get(restored, identifier), saved)
                    self.assertEqual(restored.one('PRAGMA quick_check')[0], 'ok')
                finally:
                    restored.close()
            finally:
                store.close()

    def test_snapshot_list_is_bounded_and_does_not_return_private_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory + '/db.sqlite')
            try:
                for index in range(51):
                    research.create(store, [dict(self.record(), title=str(index))], 'test')
                first = research.list_snapshots(store)
                second = research.list_snapshots(store, first['next_cursor'])
                self.assertEqual(len(first['items']), 50)
                self.assertEqual(len(second['items']), 1)
                self.assertIsNone(second['next_cursor'])
                self.assertEqual(set(first['items'][0]), {'id', 'created'})
                self.assertEqual(len({r['id'] for r in first['items'] + second['items']}), 51)
                with self.assertRaises(StoreError):
                    research.list_snapshots(store, 'invalid')
            finally:
                store.close()

    def test_real_http_auth_and_private_snapshot(self):
        server = LiveServer(); self.addCleanup(server.close)
        admin = Client(server.base); admin.login_setup()
        path = '/api/v1/research/snapshots'
        body = {'records': [self.record()]}
        self.assertEqual(Client(server.base).call('POST', path, body)[0], 401)
        csrf = admin.csrf; admin.csrf = 'wrong'
        self.assertEqual(admin.call('POST', path, body)[0], 403)
        admin.csrf = csrf
        status, result = admin.call('POST', path, body)
        self.assertEqual(status, 200)
        target = path + '/' + result['snapshot']['revision']
        self.assertEqual(admin.call('GET', path)[1]['items'][0]['id'], result['snapshot']['revision'])
        for scope in ('ro', 'rw'):
            device = Client(server.base)
            device.token = server.app.auth.create_device('research-test', scope)['token']
            self.assertEqual(device.call('GET', target)[0], 403)
            self.assertEqual(device.call('GET', path)[0], 403)
            self.assertEqual(device.call('POST', path, body)[0], 403)
        self.assertEqual(admin.call('GET', target), (200, result))
        selection = dict(snapshot_revision=result['snapshot']['revision'], expected_revision=0,
                         masked_cells=['power'], pinned=[], selected=[], limit=10)
        status, saved = admin.call('POST', target + '/selection', selection)
        self.assertEqual(status, 200)
        self.assertEqual(saved['selection_revision'], 1)
        self.assertIn('empty_selection', saved['selection']['preview']['blocking_reasons'])
        self.assertEqual(admin.call('GET', target), (200, saved))
        self.assertEqual(admin.call('POST', target + '/selection', {})[0], 400)
        self.assertEqual(admin.call('POST', path, {'records': [], 'url': 'https://example.com'})[0], 400)
