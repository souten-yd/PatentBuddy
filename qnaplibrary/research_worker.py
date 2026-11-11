"""Single low-concurrency metadata worker. No LLM or PDF acquisition."""
import threading

from . import research_discovery, research_queue


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
            except ValueError:
                # Cancellation or lease reassignment fences this worker's result.
                pass
        return True

    def _run(self):
        while not self.stopping.is_set():
            while not self.stopping.is_set() and self.run_once():
                pass
            self.wake.wait(10)
            self.wake.clear()
