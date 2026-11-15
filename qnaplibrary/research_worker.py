"""Single low-concurrency metadata worker. No LLM or PDF acquisition."""
import logging
import threading

from . import research_discovery, research_queue
from .store import StoreError

LOG = logging.getLogger('qnaplibrary.research')


class ResearchWorker:
    def __init__(self, app):
        self.app = app
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name='research-metadata')
            self.thread.start()

    def kick(self):
        self.wake.set()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=1)

    def run_once(self):
        with self.app.store.lock:
            if self.stopping.is_set():
                return False
            job = research_queue.claim(self.app.store)
        if job is None:
            return False
        key = self.app.config.secret('epo_ops_key')
        secret = self.app.config.secret('epo_ops_secret')
        result = None
        error = None
        if not key or not secret:
            error = 'credentials_not_configured'
        else:
            try:
                result = research_discovery.search(job['params']['query'], job['params']['limit'], key, secret)
            except Exception:
                # Provider response/exception text must not leak query or credentials.
                error = 'provider_failed'
        with self.app.store.lock:
            if self.stopping.is_set():
                return False
            try:
                research_queue.finish(self.app.store, job, result=result, error=error)
            except research_queue.LeaseStale:
                # Cancellation or lease reassignment fences this worker's result.
                pass
            except StoreError:
                # The provider answer cannot be stored as it stands. Settle the job as
                # a bounded failure: leaving it 'discovering' would re-send the same
                # expression to the provider on every lease expiry. Only the request
                # id is logged, never the expression, the payload or the error text.
                LOG.warning('research result rejected for request %s', job['id'])
                try:
                    research_queue.finish(self.app.store, job, error='provider_failed')
                except research_queue.LeaseStale:
                    pass
        return True

    def _run(self):
        while not self.stopping.is_set():
            try:
                while not self.stopping.is_set() and self.run_once():
                    pass
            except Exception:
                # A queue or storage fault must not end the only drainer thread: the
                # leased job would stay undispatched until a restart. The next lease
                # expiry, wake-up or 10s pause retries it.
                LOG.exception('research metadata iteration failed')
            self.wake.wait(10)
            self.wake.clear()
