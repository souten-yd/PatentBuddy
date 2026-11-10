"""Background embedding of new chunks with the configured provider (default: OpenRouter).

One daemon thread, woken after documents change. Works in small batches with a pause between
them, stops on error (status shows it) and retries only after the next change or a manual run,
so a missing key or an outage never turns into a request storm or a write loop.
"""
import logging
import threading
import time

LOG = logging.getLogger("qnaplibrary.embed")


class EmbedWorker:
    def __init__(self, store, providers, config):
        self.store, self.providers, self.config = store, providers, config
        self._wake = threading.Event()
        self._stop = False
        self.status = {"running": False, "embedded": 0, "last_error": None, "last_run": None, "model": None}
        self._thread = threading.Thread(target=self._loop, name="embed-worker", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop = True
        self._wake.set()

    def kick(self):
        if self.config.get("llm", "embedding", "auto", default=True) and self.providers.embedding_enabled():
            self._wake.set()

    def info(self):
        tag = self.providers.embedding_tag()
        d = dict(self.status, enabled=self.providers.embedding_enabled(), model=tag,
                 auto=self.config.get("llm", "embedding", "auto", default=True))
        try:
            d["pending"] = self.store.count_missing_vectors(tag)
        except Exception:
            d["pending"] = None
        return d

    def run_once(self, limit=10_000, cid=None):
        """Embed up to `limit` missing chunks now (blocking). Returns the number embedded."""
        if not self.providers.embedding_enabled():
            raise ValueError("埋め込みプロバイダが未設定です（OpenRouter の API キー等）")
        tag = self.providers.embedding_tag()
        batch = max(1, min(int(self.config.get("llm", "embedding", "batch", default=32) or 32), 128))
        done = 0
        self.status.update(running=True, last_error=None, model=tag)
        try:
            while done < limit and not self._stop:
                rows = self.store.chunks_missing_vectors(cid, min(batch, limit - done), model=tag)
                if not rows:
                    break
                prefix = self.config.get("llm", "embedding", "doc_prefix", default="") or ""
                vecs = self.providers.embed([prefix + r["title"] + "\n" + r["text"] for r in rows])
                if len(vecs) != len(rows):
                    raise ValueError("埋め込みの件数が一致しません")
                self.store.put_vectors([(r["id"], v) for r, v in zip(rows, vecs)], tag)
                done += len(rows)
                self.status["embedded"] += len(rows)
                time.sleep(0.3)
        except Exception as error:
            self.status["last_error"] = str(error)[:300]
            LOG.warning("embedding stopped: %s", error)
            raise
        finally:
            self.status.update(running=False, last_run=time.time())
        return done

    def _loop(self):
        while not self._stop:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                return
            time.sleep(2)  # let a burst of imports finish first
            try:
                self.run_once()
            except Exception:
                pass  # recorded in status; wait for the next change / manual run
