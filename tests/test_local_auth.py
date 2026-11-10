import json
import os
import socket
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from qnaplibrary.local_auth import LocalAuthServer, connect, check_private
from qnaplibrary.addon_client import AddonClient
from tests.helpers import LiveServer, Client


@unittest.skipUnless(hasattr(os, 'getuid') and os.getuid() != 0, 'requires non-root Linux')
class LocalAuthTests(unittest.TestCase):
    def test_peer_authenticated_read_only_and_restart_revocation(self):
        hub = LiveServer()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.sock'
            try:
                with mock.patch('qnaplibrary.local_auth.socket_path', return_value=path):
                    server = LocalAuthServer(hub.app.auth, hub.httpd.server_port)
                    try:
                        with self.assertRaises(OSError): connect(hub.httpd.server_port)
                        admin = Client(hub.base); admin.login_setup()
                        admin.call('POST', '/api/v1/collections', {'name': 'private'})
                        config = connect(hub.httpd.server_port)
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                        client = Client(hub.base); client.token = config['server_token']
                        self.assertEqual(client.call('GET', '/api/v1/collections')[0], 200)
                        self.assertEqual(client.call('POST', '/api/v1/collections', {'name': 'forbidden'})[0], 403)
                        self.assertEqual(client.call('GET', '/api/settings')[0], 403)
                        self.assertIsNone(hub.app.auth.device_for_token(client.token, '192.168.1.2'))
                        self.assertIsNone(hub.app.auth.device_for_token(client.token + 'x', '127.0.0.1'))
                        with mock.patch('qnaplibrary.local_auth.peer_uid', return_value=os.getuid() + 1):
                            with self.assertRaises(OSError): connect(hub.httpd.server_port)
                        with mock.patch('qnaplibrary.local_auth.peer_uid', return_value=os.getuid() + 1):
                            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as denied:
                                denied.settimeout(2); denied.connect(str(path))
                                self.assertEqual(denied.recv(4096), b'')
                        # Same-process repeated negotiation neither creates records nor writes secrets.
                        before = hub.app.store.db.total_changes
                        self.assertEqual(connect(hub.httpd.server_port), config)
                        self.assertEqual(hub.app.store.db.total_changes, before)
                        self.assertEqual(hub.app.auth.list_devices(), [])
                        with self.assertRaises(OSError): LocalAuthServer(hub.app.auth, hub.httpd.server_port)
                        from qnaplibrary.auth import Auth
                        replacement = Auth(hub.app.config, hub.app.store)
                        self.assertIsNone(replacement.device_for_token(client.token, '127.0.0.1'))
                        hub.app.config.update({'auth': {'local_auto_connect': False}})
                        self.assertIsNone(hub.app.auth.device_for_token(client.token, '127.0.0.1'))
                        with self.assertRaises(OSError): connect(hub.httpd.server_port)
                    finally: server.close()
                    self.assertFalse(path.exists())
            finally: hub.close()

    def test_manual_settings_override_and_no_secret_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = AddonClient(tmp)
            with mock.patch('qnaplibrary.local_auth.connect', return_value={'server_url': 'http://127.0.0.1:17871', 'server_token': 'ephemeral'}) as local:
                self.assertEqual(client.settings()['server_token'], 'ephemeral')
                self.assertFalse(client.path.exists())
                from qnaplibrary.addon import health_report
                self.assertEqual(health_report(True)['status'], 'healthy')
                self.assertNotIn('ephemeral', json.dumps(health_report(True)))
                client.path.write_text(json.dumps({'server_url': 'http://127.0.0.1:17871', 'server_token': 'manual'}))
                client.path.chmod(0o600)
                self.assertEqual(client.settings()['server_token'], 'manual')
                self.assertEqual(local.call_count, 1)

    def test_unsafe_endpoint_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'endpoint'; p.write_text('not a socket'); p.chmod(0o600)
            with self.assertRaises(OSError): check_private(p)
            link = Path(tmp) / 'link'; link.symlink_to(p)
            with self.assertRaises(OSError): check_private(link)
            Path(tmp).chmod(0o755)
            with self.assertRaises(OSError): check_private(Path(tmp), directory=True)


    def test_pdf_socket_is_independent_and_revoked_on_restart(self):
        hub = LiveServer()
        try:
            Client(hub.base).login_setup()
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch('qnaplibrary.local_auth.socket_path', side_effect=lambda port, scope='read': Path(tmp) / (scope + '.sock')):
                    endpoint = LocalAuthServer(hub.app.auth, hub.httpd.server_port, 'pdf_import')
                    try:
                        token = connect(hub.httpd.server_port, 'pdf_import')['server_token']
                        self.assertEqual(hub.app.auth.device_for_token(token, '127.0.0.1')['scopes'], 'pdf_import')
                        self.assertNotEqual(token, hub.app.auth.local_token('analysis'))
                        self.assertNotEqual(token, hub.app.auth.local_token('read'))
                        from qnaplibrary.auth import Auth
                        self.assertIsNone(Auth(hub.app.config, hub.app.store).device_for_token(token, '127.0.0.1'))
                        hub.app.config.update({'auth': {'local_auto_connect': False}})
                        self.assertIsNone(hub.app.auth.device_for_token(token, '127.0.0.1'))
                        with self.assertRaises(OSError): connect(hub.httpd.server_port, 'pdf_import')
                    finally: endpoint.close()
        finally: hub.close()

    def test_analysis_socket_has_independent_scoped_credential(self):
        hub = LiveServer()
        try:
            Client(hub.base).login_setup()
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch('qnaplibrary.local_auth.socket_path', side_effect=lambda port, scope='read': Path(tmp) / (scope + '.sock')):
                    reader = LocalAuthServer(hub.app.auth, hub.httpd.server_port)
                    writer = LocalAuthServer(hub.app.auth, hub.httpd.server_port, 'analysis')
                    try:
                        read = connect(hub.httpd.server_port)['server_token']
                        analysis = connect(hub.httpd.server_port, 'analysis')['server_token']
                        self.assertNotEqual(read, analysis)
                        self.assertEqual(hub.app.auth.device_for_token(read, '127.0.0.1')['scopes'], 'ro')
                        self.assertEqual(hub.app.auth.device_for_token(analysis, '127.0.0.1')['scopes'], 'analysis')
                        self.assertIsNone(hub.app.auth.device_for_token(analysis, '192.168.1.2'))
                    finally: writer.close(); reader.close()
        finally: hub.close()

    def test_embedding_socket_is_independent_and_revoked_on_restart(self):
        hub = LiveServer()
        try:
            Client(hub.base).login_setup()
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch('qnaplibrary.local_auth.socket_path', side_effect=lambda port, scope='read': Path(tmp) / (scope + '.sock')):
                    endpoint = LocalAuthServer(hub.app.auth, hub.httpd.server_port, 'embedding')
                    try:
                        token = connect(hub.httpd.server_port, 'embedding')['server_token']
                        self.assertEqual(hub.app.auth.device_for_token(token, '127.0.0.1')['scopes'], 'embedding')
                        self.assertNotEqual(token, hub.app.auth.local_token('analysis'))
                        self.assertNotEqual(token, hub.app.auth.local_token('read'))
                        from qnaplibrary.auth import Auth
                        self.assertIsNone(Auth(hub.app.config, hub.app.store).device_for_token(token, '127.0.0.1'))
                        hub.app.config.update({'auth': {'local_auto_connect': False}})
                        self.assertIsNone(hub.app.auth.device_for_token(token, '127.0.0.1'))
                        with self.assertRaises(OSError): connect(hub.httpd.server_port, 'embedding')
                    finally: endpoint.close()
        finally: hub.close()
