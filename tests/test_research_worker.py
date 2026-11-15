"""Worker behaviour: fenced completion, no leaking details, lease recovery."""
import json
import pathlib
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qnaplibrary import debuglog, research_queue as queue
from qnaplibrary.config import Config
from qnaplibrary.research_worker import ResearchWorker
from qnaplibrary.store import Store, StoreError

RESULT = dict(records=[dict(publication='EP1004359B1', language='en', family=None, title='Synthetic',
                            sources=['epo_ops'], cells=[])],
              provider='epo_ops', fetched=1, reported_total=5, truncated=True)
# Text a provider might raise. It repeats the query and a credential-looking value
# on purpose: neither one may survive anywhere in the worker's result.
LEAKY = 'ops 502 q=ta%3Dsynthetic-query key=op-secret-value-9137'


def wait_for(check, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    return None


def research_faults():
    """Worker faults recorded for /api/debug/bundle (RAM ring, never on disk)."""
    return [e for e in list(debuglog.ERRORS) if 'research metadata iteration failed' in str(e.get('msg'))]


class WorkerTests(unittest.TestCase):
    def setUp(self):
        debuglog.setup('WARNING', stderr=False)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name + '/worker.sqlite')
        self.addCleanup(self.store.close)
        self.config = Config(self.directory.name)
        self.app = SimpleNamespace(store=self.store, config=self.config)
        self.worker = ResearchWorker(self.app)
        self.addCleanup(self.worker.close)
        self.value = dict(id='a' * 32, query='ta=inverter', limit=10, confirm_public=True)

    def create(self, identifier='b' * 31 + '1', **changes):
        queue.create(self.store, dict(self.value, id=identifier, **changes), 'admin')
        return identifier

    def claim_spy(self, claimed):
        real_claim = queue.claim

        def spy(store):
            job = real_claim(store)
            if job:
                claimed.append(job)
            return job
        return spy

    def test_missing_credentials_finishes_as_waiting(self):
        identifier = self.create()
        with patch('qnaplibrary.research_discovery.search') as search:
            self.assertTrue(self.worker.run_once())
            search.assert_not_called()
        row = queue.get(self.store, identifier)
        self.assertEqual(row['state'], 'waiting_credentials')
        self.assertEqual(row['error'], 'credentials_not_configured')
        self.assertIsNone(row['snapshot_id'])
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0], 0)
        # A waiting request is never picked up again until it is explicitly retried.
        with patch('qnaplibrary.research_discovery.search') as search:
            self.assertFalse(self.worker.run_once())
            search.assert_not_called()
        self.assertEqual(queue.get(self.store, identifier)['state'], 'waiting_credentials')
        retried = queue.transition(self.store, identifier, row['revision'], 'retry', 'admin')
        self.assertEqual((retried['state'], retried['error']), ('queued', ''))

    def test_provider_exception_finishes_as_bounded_code_without_detail(self):
        identifier = self.create()
        with patch.object(self.config, 'secret', return_value='op-secret-value-9137'), \
                patch('qnaplibrary.research_discovery.search', side_effect=RuntimeError(LEAKY)):
            self.assertTrue(self.worker.run_once())
        row = queue.get(self.store, identifier)
        self.assertEqual((row['state'], row['error']), ('failed', 'provider_failed'))
        self.assertIsNone(row['snapshot_id'])
        audit = [dict(r) for r in self.store.q("SELECT actor,action,detail FROM audit")]
        on_disk = b''.join(p.read_bytes() for p in sorted(pathlib.Path(self.directory.name).rglob('*')) if p.is_file())
        surfaces = [json.dumps(row), json.dumps(audit), on_disk.decode('utf-8', 'replace')]
        for surface in surfaces:
            self.assertNotIn('op-secret-value-9137', surface)
            self.assertNotIn('synthetic-query', surface)
        self.assertIn('research.failed', [r['action'] for r in audit])
        # A failed request needs an explicit retry; the worker never loops on it.
        with patch.object(self.config, 'secret', return_value='key'), \
                patch('qnaplibrary.research_discovery.search') as search:
            self.assertFalse(self.worker.run_once())
            search.assert_not_called()
        self.assertEqual(queue.transition(self.store, identifier, row['revision'], 'retry', 'admin')['state'], 'queued')

    def test_stopping_worker_leaves_bounded_lease_that_recovers(self):
        identifier = self.create()
        claimed = []

        def search(*args):
            self.worker.stopping.set()  # close() lands while the provider call is in flight
            return RESULT

        with patch.object(queue, 'claim', side_effect=self.claim_spy(claimed)), \
                patch.object(self.config, 'secret', return_value='key'), \
                patch('qnaplibrary.research_discovery.search', side_effect=search):
            self.assertFalse(self.worker.run_once())
        abandoned = claimed[0]
        lease_until = self.store.one('SELECT lease_until FROM research_requests WHERE id=?', (identifier,))[0]
        self.assertGreater(lease_until, time.time())
        self.assertLessEqual(lease_until - time.time(), 180)
        self.assertEqual(abandoned['state'], 'discovering')
        self.assertNotIn('lease_until', queue.get(self.store, identifier))
        self.assertEqual(queue.get(self.store, identifier)['state'], 'discovering')
        self.assertEqual(queue.get(self.store, identifier)['error'], '')
        # While the lease lives nobody else may take the job and the stopped
        # worker never finishes it.
        with patch.object(self.config, 'secret', return_value='key'), \
                patch('qnaplibrary.research_discovery.search', return_value=RESULT):
            self.assertIsNone(queue.claim(self.store))
            self.assertFalse(ResearchWorker(self.app).run_once())
        self.assertEqual(queue.get(self.store, identifier)['state'], 'discovering')
        # The abandoned lease expires and only then fences the stopped worker.
        self.store.db.execute('UPDATE research_requests SET lease_until=?', (time.time() - 1,))
        with self.assertRaises(queue.LeaseStale):
            queue.finish(self.store, abandoned, RESULT)
        self.assertEqual(queue.get(self.store, identifier)['state'], 'discovering')
        with patch.object(self.config, 'secret', return_value='key'), \
                patch('qnaplibrary.research_discovery.search', return_value=RESULT):
            self.assertTrue(ResearchWorker(self.app).run_once())
        done = queue.get(self.store, identifier)
        self.assertEqual(done['state'], 'awaiting_selection')
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0], 1)
        self.assertNotIn('lease', json.dumps(done))

    def test_fenced_finish_neither_logs_nor_stops_the_thread(self):
        canceled_id, running_id = self.create('c' * 31 + '1'), self.create('c' * 31 + '2')
        claimed, calls, faults = [], [], len(research_faults())

        def search(query, limit, key, secret):
            calls.append(query)
            if len(calls) == 1:
                # The user cancels while this job is in flight: finish must be fenced.
                queue.transition(self.store, claimed[0]['id'], claimed[0]['revision'], 'cancel', 'admin')
            return RESULT

        with patch.object(queue, 'claim', side_effect=self.claim_spy(claimed)), \
                patch.object(self.config, 'secret', return_value='key'), \
                patch('qnaplibrary.research_discovery.search', side_effect=search):
            self.worker.start()
            self.worker.start()  # idempotent: one worker thread
            finished = wait_for(lambda: queue.get(self.store, running_id)['state'] == 'awaiting_selection')
            threads = [t for t in threading.enumerate() if t.name == 'research-metadata']
        self.assertTrue(finished, 'worker thread stopped serving after a fenced finish')
        self.assertEqual(len(threads), 1)
        self.assertEqual(queue.get(self.store, canceled_id)['state'], 'canceled')
        self.assertEqual(queue.get(self.store, canceled_id)['error'], '')
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.store.one('SELECT count(*) FROM research_snapshots')[0], 1)
        # Dropping a fenced result is normal operation, not a fault to report.
        self.assertEqual(len(research_faults()), faults)

    def test_close_stops_claiming_and_finishing(self):
        self.worker.start()
        self.worker.close()  # joins the thread, so nothing may be claimed afterwards
        self.assertFalse(self.worker.thread.is_alive())
        identifier = self.create()
        with patch.object(queue, 'claim') as claim:
            self.assertFalse(self.worker.run_once())
            claim.assert_not_called()
        self.assertEqual(queue.get(self.store, identifier)['state'], 'queued')

    def test_unexpected_queue_error_is_logged_and_thread_survives(self):
        # A storage/queue fault must not end the only drainer thread, and it has to
        # reach /api/debug/bundle instead of vanishing with the worker's traceback.
        identifier = self.create()
        real_claim, remaining = queue.claim, [1]

        def flaky(store):
            if remaining[0]:
                remaining[0] -= 1
                raise StoreError('database disk image is malformed')
            return real_claim(store)

        with patch.object(queue, 'claim', side_effect=flaky), \
                patch.object(self.config, 'secret', return_value='key'), \
                patch('qnaplibrary.research_discovery.search', return_value=RESULT):
            self.worker.start()
            reported = wait_for(research_faults)
            self.worker.kick()
            completed = wait_for(lambda: queue.get(self.store, identifier)['state'] == 'awaiting_selection')
        self.assertTrue(reported, 'queue fault never reached the debug ring')
        self.assertTrue(completed, 'worker never served the next job')
        self.assertTrue(self.worker.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
