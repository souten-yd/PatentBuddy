import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from qnaplibrary.addon_client import AddonClient, AddonError, validate_url
from qnaplibrary.server import AddonShell, Server
from tests.helpers import Client, LiveServer


class AddonClientTests(unittest.TestCase):
    def test_identity_is_verified_before_private_access(self):
        client = AddonClient('/unused')
        headers = {'Authorization': 'Bearer synthetic', 'X-Control-Deck-Addon-ID': 'patent-buddy'}
        identity = {'active': True, 'addon_id': 'patent-buddy', 'subject': 'context:1',
                    'expires_at': int(time.time()) + 60, 'granted_capabilities': ['context.read']}
        with mock.patch('qnaplibrary.addon_client.request_json', return_value=identity) as upstream:
            self.assertEqual(client.authenticate(headers)['subject'], 'context:1')
            self.assertEqual(upstream.call_args.args[2], '/api/v1/addon-runtime/token/introspect')
        for patch in ({'active': False}, {'addon_id': 'other'}, {'expires_at': 0},
                      {'expires_at': True}, {'expires_at': int(time.time()) + 3600}, {'granted_capabilities': []}):
            with mock.patch('qnaplibrary.addon_client.request_json', return_value=dict(identity, **patch)):
                with self.assertRaises(AddonError): client.authenticate(headers)
        with self.assertRaises(AddonError): client.authenticate({})

    def test_remote_plaintext_and_credentials_in_url_rejected(self):
        for url in ('http://192.168.1.2:17871', 'https://example.com:443',
                    'http://user:pass@127.0.0.1:17871', 'http://127.0.0.1:17871/?token=secret'):
            with self.assertRaises(AddonError): validate_url(url)
        self.assertEqual(validate_url('http://127.0.0.1:17871'), 'http://127.0.0.1:17871')
        self.assertEqual(validate_url('https://192.168.1.2:17871'), 'https://192.168.1.2:17871')

    def test_connection_file_requires_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'connection.json'
            path.write_text(json.dumps({'server_url': 'http://127.0.0.1:17871', 'server_token': 'secret'}))
            path.chmod(0o644)
            with self.assertRaises(AddonError): AddonClient(tmp).settings()
            path.chmod(0o600)
            self.assertEqual(AddonClient(tmp).settings()['server_url'], 'http://127.0.0.1:17871')

    def test_authenticated_addon_reads_only_authoritative_server(self):
        hub = LiveServer()
        try:
            admin = Client(hub.base); admin.login_setup()
            admin.call('POST', '/api/v1/collections', {'name': 'synthetic'})
            admin.call('POST', '/api/v1/collections/synthetic/documents', {'documents': [
                {'id': 'JP-SYN', 'title': '合成電池', 'body': '電池の構造を説明する。'}]})
            _, issued = admin.call('POST', '/api/devices', {'name': 'addon-test', 'scopes': 'ro'})
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'connection.json'
                path.write_text(json.dumps({'server_url': hub.base, 'server_token': issued['token']})); path.chmod(0o600)
                app = AddonShell(tmp); server = Server(('127.0.0.1', 0), app)
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    browser = Client('http://127.0.0.1:%d' % server.server_port)
                    self.assertEqual(browser.call('GET', '/addon/v1/status')[0], 401)
                    self.assertEqual(browser.call('GET', '/addon/v1/embedding-jobs')[0], 401)
                    self.assertEqual(browser.call('POST', '/addon/v1/embedding-jobs', {})[0], 401)
                    with mock.patch.object(app.client, 'authenticate', return_value={'subject': '1'}):
                        self.assertEqual(browser.call('GET', '/addon/v1/embedding-jobs'), (200, {'items': []}))
                        with mock.patch.object(app.embedding_jobs, 'start') as start:
                            for invalid in ([], {'model_ref': 'untrusted'}, {'url': 'https://example.test'}):
                                self.assertEqual(browser.call('POST', '/addon/v1/embedding-jobs', invalid)[0], 400)
                            start.assert_not_called()

                    with mock.patch.object(app.client, 'authenticate', return_value={'subject': 'context:1'}):
                        status, state = browser.call('GET', '/addon/v1/status')
                        self.assertEqual(status, 200)
                        self.assertTrue(state['server']['token_configured'])
                        self.assertNotIn(issued['token'], json.dumps(state))
                        status, found = browser.call('POST', '/addon/v1/search', {'q': '電池'})
                        self.assertEqual(status, 200)
                        self.assertEqual(len(found['results']), 1)
                        doc_id = found['results'][0]['doc_id']
                        status, doc = browser.call('GET', '/addon/v1/documents/%d' % doc_id)
                        self.assertEqual(status, 200)
                        self.assertEqual(doc['body'], '電池の構造を説明する。')
                        self.assertEqual(browser.call('GET', '/api/debug/bundle')[0], 404)
                        self.assertEqual(browser.call('POST', '/addon/v1/search', {'q': []})[0], 400)
                    self.assertFalse((Path(tmp) / 'library.sqlite3').exists())
                finally:
                    app.pdf_jobs.close(); app.jobs.close(); app.embedding_jobs.close()
                    server.shutdown(); server.server_close(); thread.join()
        finally: hub.close()
