"""In-RAM logging and the AI-readable debug bundle.

Nothing here writes to disk on its own: records live in bounded deques. A bundle (JSON) is
built on demand by /api/debug/bundle so an AI can inspect failures and propose fixes.
Secrets are never logged; `redact` removes known secret-looking values from dicts.
"""
import collections
import logging
import platform
import sys
import threading
import time
import traceback

LOG = logging.getLogger("qnaplibrary")
_lock = threading.Lock()
RECORDS = collections.deque(maxlen=1500)
ERRORS = collections.deque(maxlen=200)
REQUESTS = collections.deque(maxlen=300)
SEARCHES = collections.deque(maxlen=100)
SLOW = collections.deque(maxlen=100)
STARTED = time.time()
SECRET_KEYS = ("key", "token", "secret", "password", "passcode", "authorization", "cookie")


class RingHandler(logging.Handler):
    def emit(self, record):
        try:
            item = {"ts": round(record.created, 3), "level": record.levelname,
                    "logger": record.name, "msg": record.getMessage()}
            if record.exc_info:
                item["exc"] = "".join(traceback.format_exception(*record.exc_info))[-4000:]
            with _lock:
                RECORDS.append(item)
                if record.levelno >= logging.ERROR:
                    ERRORS.append(item)
        except Exception:  # pragma: no cover - logging must never raise
            pass


def setup(level="INFO", stderr=True):
    root = logging.getLogger("qnaplibrary")
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    if not any(isinstance(h, RingHandler) for h in root.handlers):
        root.addHandler(RingHandler())
        if stderr:
            h = logging.StreamHandler(sys.stderr)
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            h.setLevel(logging.WARNING)
            root.addHandler(h)


def note_request(method, path, status, ms, actor):
    with _lock:
        REQUESTS.append({"ts": round(time.time(), 3), "method": method, "path": path[:200],
                         "status": status, "ms": round(ms, 1), "actor": actor})
        if ms > 1500:
            SLOW.append({"ts": round(time.time(), 3), "kind": "request", "path": path[:200], "ms": round(ms, 1)})


def note_search(trace):
    with _lock:
        SEARCHES.append(trace)


def redact(value, depth=0):
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if not isinstance(v, (dict, list)) and any(s in str(k).lower() for s in SECRET_KEYS) and \
                    not str(k).lower().endswith(("_set", "configured", "fingerprint")):
                out[k] = "***" if v else v
            else:
                out[k] = redact(v, depth + 1)
        return out
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:200]]
    return value


def bundle(extra=None):
    with _lock:
        data = {
            "generated_at": time.time(),
            "uptime_s": round(time.time() - STARTED, 1),
            "python": sys.version,
            "platform": platform.platform(),
            "errors": list(ERRORS)[-100:],
            "log": list(RECORDS)[-400:],
            "requests": list(REQUESTS)[-150:],
            "slow": list(SLOW),
            "searches": list(SEARCHES)[-50:],
            "hint": ("QnapLibrary debug bundle. 'errors' has tracebacks; 'searches' has per-stage "
                     "candidate counts and timings; 'store' has DB stats. Secrets are redacted."),
        }
    if extra:
        data.update(redact(extra))
    return data
