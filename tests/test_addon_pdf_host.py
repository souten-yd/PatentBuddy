import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from qnaplibrary.addon_client import AddonClient, AddonError
from qnaplibrary.addon_pdf_host import PDFHostSession, HOST_BYTES

GRANT = 'grant:12345678-1234-1234-1234-123456789abc'


class PDFHostTests(unittest.TestCase):
    def session(self):
        client = AddonClient('/unused')
        client.authenticate = Mock(return_value={'subject': '1', 'actor_subject': 'user:1',
            'addon_id': 'patent-buddy', 'expires_at': int(time.time()) + 600,
            'granted_capabilities': list(PDFHostSession.required)})
        session = PDFHostSession(client, {'Authorization': 'Bearer synthetic-browser'})
        session.job_id = 'test-job'
        return session

    def grant_value(self):
        return {'grant_id': GRANT, 'kind': 'read', 'name': 'test.pdf', 'size': 100, 'expires_at': time.time() + 10}

    def test_only_scoped_selected_pdf_is_read(self):
        session = self.session()
        for change in ({'kind': 'export'}, {'size': True}, {'size': 51 * 1024 ** 2}, {'name': 'x.txt'}, {'expires_at': 0}):
            session.call = Mock(return_value=dict(self.grant_value(), **change))
            with self.assertRaises(AddonError): session.grant(GRANT)
        session.call = Mock(return_value=self.grant_value())
        self.assertEqual(session.grant(GRANT)['size'], 100)
        session.call.reset_mock()
        for value in ('/tmp/private.pdf', '../elsewhere', GRANT + '/content'):
            with self.assertRaises(AddonError): session.grant(value)
        session.call.assert_not_called()

    def response(self, **values):
        return dict({'request_id': 'request-1', 'state': 'granted', 'job_id': 'test-job',
                     'owner': 'addon:patent-buddy', 'lease_id': 'lease-1', 'device_id': 'host',
                     'granted_bytes': HOST_BYTES}, **values)

    def test_cpu_only_admission_and_cleanup(self):
        session = self.session()
        lease = {'lease_id': 'lease-1', 'state': 'active', 'job_id': 'test-job',
                 'owner': 'addon:patent-buddy', 'device_id': 'host', 'reserved_bytes': HOST_BYTES}
        session.call = Mock(side_effect=[self.response(), lease, dict(lease, state='released'), {}])
        session.acquire_cpu()
        body = session.call.call_args_list[0].args[2]
        self.assertEqual(body['host_bytes'], HOST_BYTES)
        self.assertEqual(body['preferred_devices'], ['host'])
        session.release_cpu()
        self.assertIsNone(session.lease_id)
        self.assertIsNone(session.request_id)
        for changed in ({'device_id': 'gpu0'}, {'granted_bytes': HOST_BYTES - 1}, {'owner': 'addon:other'}, {'job_id': 'other-job'}):
            session = self.session(); session.call = Mock(return_value=self.response(**changed))
            with self.assertRaises(AddonError): session.acquire_cpu()
            self.assertEqual(session.call.call_count, 1)

    def test_fast_pages_coalesce_under_host_2hz_limit(self):
        session = self.session(); session.call = Mock(return_value={})
        with patch('qnaplibrary.addon_pdf_host.time.monotonic', return_value=5):
            session.progress('extracting', 1, 15)
            for page in range(2, 15): session.progress('extracting', page, 15)
        self.assertEqual(session.call.call_count, 1)
        with patch('qnaplibrary.addon_pdf_host.time.monotonic', return_value=7):
            session.progress('extracting', 15, 15)
        self.assertEqual(session.call.call_count, 2)

    def test_revoked_lease_cannot_continue(self):
        session = self.session(); session.lease_id = 'lease-1'
        for state in ('expired', 'canceled', 'released'):
            with self.assertRaises(AddonError):
                session._check_lease({'lease_id': 'lease-1', 'state': state, 'job_id': 'test-job',
                                     'owner': 'addon:patent-buddy', 'device_id': 'host', 'reserved_bytes': HOST_BYTES})


if __name__ == '__main__': unittest.main()
