"""K1d verified Host streaming: an unproved Host never receives source text."""
import json
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

from qnaplibrary.addon_client import AddonError
from qnaplibrary.addon_host import HostSession

PROOF = {
    'execution_policy': 'local_only',
    'revision_kind': 'host_process_file_metadata_v1',
    'model_ref': '1' * 64, 'runtime_ref': '2' * 64,
}
TEXT = '特許未公開の試験用文面'


def event(kind, **extra):
    return ('data: ' + json.dumps({'type': kind, **extra}, ensure_ascii=False) + '\n').encode()


class Response:
    status = 200

    def __init__(self, events):
        self.lines = list(events)

    def readline(self, _limit):
        return self.lines.pop(0) if self.lines else b''


class Connection:
    events = []
    last = None

    def __init__(self, host, port, timeout=None):
        self.sock = object()
        self.sent = None
        self.closed = False
        Connection.last = self

    def connect(self):
        pass

    def request(self, method, path, body=None, headers=None):
        self.sent = (method, path, json.loads(body), headers)

    def getresponse(self):
        return Response(self.events)

    def close(self):
        self.closed = True


class HostProvenanceStreamTests(unittest.TestCase):
    def setUp(self):
        Connection.events = []
        Connection.last = None
        self.patch = mock.patch('qnaplibrary.addon_host.http.client.HTTPConnection', Connection)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.host = object.__new__(HostSession)
        self.host.client = SimpleNamespace(host_url='http://127.0.0.1:8765')
        self.host.headers = {'Authorization': 'Bearer synthetic'}
        self.host.lock = threading.RLock()
        self.host.aborted = threading.Event()
        self.host.transport = None
        self.host.generation_provenance = None
        self.host.provenance_available = lambda: True
        self.host.local_available = lambda: True

    def test_capability_envelope_fail_closed(self):
        self.host.provenance_available = HostSession.provenance_available.__get__(
            self.host, HostSession)
        for response in (None, [], {}, {'text.generate': None},
                         {'text.generate': {'request_options': None}},
                         {'text.generate': {
                             'available': True, 'local_only_available': True,
                             'request_options': {'local_only': True,
                                                 'require_provenance': {'supported': True}}}}):
            with self.subTest(response=response):
                self.host.call = lambda *args, result=response: result
                self.assertFalse(self.host.provenance_available())
        self.host.call = lambda *args: {'text.generate': {
            'available': True, 'local_only_available': True,
            'request_options': {
                'local_only': {'supported': True},
                'require_provenance': {'supported': True}}}}
        self.assertTrue(self.host.provenance_available())

    def test_unverified_host_never_receives_secret_document(self):
        self.host.provenance_available = lambda: False
        with self.assertRaises(AddonError):
            self.host.stream([{'role': 'user', 'content': TEXT}], require_provenance=True)
        self.assertIsNone(Connection.last)
        self.assertIsNone(self.host.generation_provenance)

    def test_local_only_provenance_attested_and_not_model_supplied(self):
        Connection.events = [event('content', content='{"items":[]}'),
                             event('provenance', provenance=PROOF),
                             event('done')]
        result = self.host.stream([{'role': 'user', 'content': TEXT}], require_provenance=True)
        self.assertEqual(result, '{"items":[]}')
        self.assertEqual(self.host.generation_provenance, PROOF)
        sent = Connection.last.sent[2]
        self.assertIs(sent['local_only'], True)
        self.assertIs(sent['require_provenance'], True)
        self.assertIn(TEXT, sent['messages'][0]['content'])
        self.assertTrue(Connection.last.closed)

    def test_missing_or_duplicate_provenance_is_rejected(self):
        for events in ([event('content', content='text'), event('done')],
                       [event('provenance', provenance=PROOF),
                        event('provenance', provenance=PROOF), event('done')]):
            with self.subTest(case=len(events)):
                Connection.events = events
                with self.assertRaises(AddonError):
                    self.host.stream([{'role': 'user', 'content': TEXT}], require_provenance=True)
                self.assertIsNone(self.host.generation_provenance)

    def test_cloud_provenance_rejected(self):
        Connection.events = [event('content', content='text'),
                             event('provenance', provenance=dict(PROOF, execution_policy='cloud')),
                             event('done')]
        with self.assertRaises(AddonError):
            self.host.stream([{'role': 'user', 'content': TEXT}], require_provenance=True)
        self.assertIsNone(self.host.generation_provenance)

    def test_original_summary_stream_uses_legacy_contract_without_proof(self):
        Connection.events = [event('content', content='legacy summary'), event('done')]
        self.assertEqual(self.host.stream([{'role': 'user', 'content': 'public'}]), 'legacy summary')
        self.assertNotIn('require_provenance', Connection.last.sent[2])
        self.assertIsNone(self.host.generation_provenance)

    def test_no_content_sent_when_aborted(self):
        self.host.aborted.set()
        with self.assertRaises(AddonError):
            self.host.stream([{'role': 'user', 'content': TEXT}], require_provenance=True)
        self.assertIsNone(Connection.last)


if __name__ == '__main__':
    unittest.main()
