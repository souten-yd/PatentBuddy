import time
import unittest
from unittest import mock
from qnaplibrary.addon_client import AddonClient, AddonError
from qnaplibrary.addon_host import HostSession, REQUIRED


class HostSessionTests(unittest.TestCase):
    def make_session(self):
        client = AddonClient('/unused')
        identity = {'subject': '1', 'actor_subject': 'user:1', 'expires_at': int(time.time()) + 600,
                    'granted_capabilities': list(REQUIRED)}
        client.authenticate = mock.Mock(return_value=identity)
        session = HostSession(client, {'Authorization': 'Bearer synthetic-browser'})
        return client, session

    def test_legacy_or_unverified_host_receives_no_prompt(self):
        for caps in ({}, {'available': True}, {'available': True, 'local_only_available': True},
                     {'available': True, 'local_only_available': False,
                      'request_options': {'local_only': {'supported': True}}}):
            _, session = self.make_session()
            session.call = mock.Mock(return_value={'text.generate': caps})
            with self.assertRaises(AddonError): session.complete([{'role': 'user', 'content': 'private'}])
            self.assertEqual(session.call.call_count, 1)
            self.assertEqual(session.call.call_args.args, ('GET', '/ai/capabilities'))

    def test_private_request_requires_local_policy_response(self):
        caps = {'text.generate': {'available': True, 'local_only_available': True,
                                 'request_options': {'local_only': {'supported': True}}}}
        for response in ({'content': 'not attested'}, {'content': '', 'execution_policy': 'local_only'},
                         {'content': 'answer', 'execution_policy': 'local_only'}):
            _, session = self.make_session()
            session.call = mock.Mock(side_effect=[caps, response])
            if response.get('execution_policy') == 'local_only' and response['content']:
                self.assertEqual(session.complete([{'role': 'user', 'content': 'private'}]), 'answer')
            else:
                with self.assertRaises(AddonError): session.complete([{'role': 'user', 'content': 'private'}])
            body = session.call.call_args.args[2]
            self.assertIs(body['local_only'], True)
            self.assertNotIn('model', body)
            self.assertNotIn('base_url', body)

    def test_job_credential_cannot_switch_owner_or_subject(self):
        client, session = self.make_session()
        session.call = mock.Mock(return_value={'created': True, 'job': {'id': 'job-1'}, 'access_token': 'synthetic-job'})
        job_identity = dict(client.authenticate.return_value, subject='job:job-1')
        client.authenticate.return_value = job_identity
        self.assertEqual(session.create_job(), 'job-1')
        original = dict(session.headers)
        for change in ({'subject': 'job:other'}, {'actor_subject': 'user:2'}, {'granted_capabilities': []}):
            client.authenticate.return_value = dict(job_identity, **change)
            with self.assertRaises(AddonError): session._replace_credential({'access_token': 'changed'})
            self.assertEqual(session.headers, original)
        client.authenticate.return_value = job_identity
        session.identity = dict(job_identity, expires_at=int(time.time()) + 10)
        session.call = mock.Mock(side_effect=[{'access_token': 'renewed'}, {'host_job_id': 'job-1', 'cancel_requested': True}])
        self.assertTrue(session.heartbeat()['cancel_requested'])
        self.assertEqual(session.headers['Authorization'], 'Bearer renewed')

    def test_missing_capability_is_rejected(self):
        client, _ = self.make_session()
        client.authenticate.return_value['granted_capabilities'] = ['context.read']
        with self.assertRaises(AddonError): HostSession(client, {'Authorization': 'Bearer synthetic'})


class StreamCancellationTests(unittest.TestCase):
    def test_abort_disconnects_blocked_stream_and_never_returns_partial_text(self):
        import http.server
        import threading
        received = threading.Event()
        release = threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                self.wfile.write(b'data: {"type":"content","content":"partial"}\n\n');self.wfile.flush()
                received.set();release.wait(3)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            _, session = HostSessionTests().make_session()
            session.client.host_url = 'http://127.0.0.1:%d' % server.server_port
            session.local_available = lambda: True
            errors = []
            def run():
                try: session.stream([{'role': 'user', 'content': 'synthetic'}])
                except AddonError as error: errors.append(error.status)
            worker = threading.Thread(target=run, daemon=True);worker.start()
            self.assertTrue(received.wait(2));session.abort();worker.join(timeout=2)
            self.assertFalse(worker.is_alive());self.assertEqual(errors, [502])
        finally:
            release.set();server.shutdown();server.server_close();thread.join(timeout=2)
