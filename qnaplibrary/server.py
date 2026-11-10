"""HTTP server and application wiring (standard library only)."""
import argparse
import gzip
import hashlib
import json
import logging
import mimetypes
import os
import re
import signal
import socket
import ssl
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import APP_NAME, DEFAULT_PORT, VERSION, api, debuglog, webauthn
from .auth import Auth
from .config import Config
from .embedworker import EmbedWorker
from .notify import Notifier
from .watch import Scheduler, Watches
from .llm import Providers
from .patents import Patents
from .search import Searcher
from .store import Store
from .updater import Updater

LOG = logging.getLogger("qnaplibrary.server")
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 4 * 1024 * 1024
MAX_IMPORT_BODY = 96 * 1024 * 1024
SESSION_COOKIE = "ql_session"


class HTTPError(Exception):
    def __init__(self, status, message, extra=None):
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra or {}


class App:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = Config(self.data_dir)
        self.store = Store(self.data_dir / "library.sqlite3")
        self.auth = Auth(self.config, self.store)
        self.providers = Providers(self.config)
        self.searcher = Searcher(self.store, self.config, self._embedder, self._vector_model)
        self.embedder = EmbedWorker(self.store, self.providers, self.config)
        self.store.on_change = self.embedder.kick
        self.notifier = Notifier(self.config, self.store)
        self.watches = Watches(self)
        self.scheduler = Scheduler(self)
        self.patents = Patents(self.store, self.searcher, self.providers)
        self.challenges = webauthn.Challenges()
        self.exit_code = 0
        self.httpd = None
        self.updater = Updater(self.config, self.data_dir, shutdown=self.request_shutdown)
        self.static = StaticCache(WEB_DIR)
        self.started = time.time()

    def _embedder(self, texts, query=False):
        if not self.providers.embedding_enabled():
            return None
        return self.providers.embed(texts, query=query)

    def _vector_model(self):
        return self.providers.embedding_tag() if self.providers.embedding_enabled() else None

    def request_shutdown(self, code=0):
        self.exit_code = code
        if self.httpd:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()

    def debug_bundle(self):
        return debuglog.bundle({
            "version": VERSION, "app": APP_NAME, "data_dir": str(self.data_dir),
            "install_mode": self.updater.mode, "update": self.updater.status(),
            "store": self.store.stats(), "vectors": self.searcher.vectors.info(),
            "embedding": self.embedder.info(), "vector_models": self.store.vector_models(),
            "scheduler": self.scheduler.status,
            "watches": [{k: w[k] for k in ("id", "name", "connector", "last_run", "last_status", "new_hits")} for w in self.watches.list()],
            "settings": self.config.all(),
            "secrets": {k: self.config.secret_status(k) for k in api.SECRET_NAMES},
            "llm_providers": [{"id": p["id"], "type": p["type"], "base_url": p["base_url"], "model": p.get("model")}
                              for p in self.providers.list()],
        })


class StaticCache:
    """Serve the management web from RAM with gzip and strong ETags (zero disk reads after warm-up)."""

    def __init__(self, root):
        self.root = Path(root)
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, rel):
        rel = rel.lstrip("/") or "index.html"
        if not re.fullmatch(r"[A-Za-z0-9_\-./]+", rel) or ".." in rel:
            return None
        with self._lock:
            if rel in self._cache:
                return self._cache[rel]
        path = (self.root / rel).resolve()
        if not str(path).startswith(str(self.root.resolve())) or not path.is_file():
            return None
        raw = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml", "application/json"):
            ctype += "; charset=utf-8"
        entry = {"raw": raw, "gz": gzip.compress(raw, 6), "etag": '"%s"' % hashlib.sha256(raw).hexdigest()[:20],
                 "type": ctype}
        with self._lock:
            self._cache[rel] = entry
        return entry


class Request:
    """Thin request wrapper passed to API handlers."""

    def __init__(self, handler, method, path, query, params):
        self.h = handler
        self.method = method
        self.path = path
        self.query = query
        self.params = params
        self.app = handler.server.app
        self.ip = handler.client_address[0]
        self.actor = None       # "admin" | "device:<name>"
        self.session = None
        self.session_id = None
        self.device = None
        self._body = None

    def arg(self, name, default=None):
        v = self.query.get(name)
        return v[0] if v else default

    def json(self, limit=MAX_BODY):
        if self._body is None:
            length = int(self.h.headers.get("Content-Length") or 0)
            if length > limit:
                raise HTTPError(413, "リクエストが大きすぎます")
            raw = self.h.rfile.read(length) if length else b""
            if not raw:
                self._body = {}
            else:
                try:
                    self._body = json.loads(raw.decode("utf-8"))
                except ValueError:
                    raise HTTPError(400, "JSON が不正です")
        return self._body

    def is_https(self):
        """Direct TLS, or Tailscale Serve / a local reverse proxy terminating TLS on this host.

        X-Forwarded-Proto is trusted only from loopback peers (Serve connects from 127.0.0.1).
        """
        if self.h.server.tls:
            return True
        if self.ip not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            return False
        host = (self.h.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return (self.h.headers.get("X-Forwarded-Proto") or "").lower() == "https" or host.endswith(".ts.net")

    def origin(self):
        scheme = "https" if self.is_https() else "http"
        host = self.h.headers.get("Host", "")
        return "%s://%s" % (scheme, host)

    def rp_id(self):
        configured = self.app.config.get("auth", "rp_id", default="")
        if configured:
            return configured
        return (self.h.headers.get("Host", "") or "localhost").rsplit(":", 1)[0].strip("[]")


class Handler(BaseHTTPRequestHandler):
    server_version = "QnapLibrary/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # no access log on disk
        return

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PUT, PATCH, DELETE")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # -----------------------------------------------------------------------
    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                         "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        # No HSTS on purpose: plain http on the LAN must keep working for the same host name.

    def send_json(self, status, data, headers=None):
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        gz = len(raw) > 1400 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            raw = gzip.compress(raw, 5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self._security_headers()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)
        return status

    def start_stream(self, ctype="text/event-stream"):
        self.send_response(200)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self._security_headers()
        self.end_headers()
        self.close_connection = True

    def stream_event(self, data):
        self.wfile.write(("data: %s\n\n" % json.dumps(data, ensure_ascii=False)).encode("utf-8"))
        self.wfile.flush()

    def send_bytes(self, status, raw, ctype, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self._security_headers()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
        return status

    def _static(self, path):
        entry = self.server.app.static.get(path)
        if entry is None and not path.startswith("/api") and "." not in path.rsplit("/", 1)[-1]:
            entry = self.server.app.static.get("index.html")  # SPA fallback
        if entry is None:
            return self.send_json(404, {"error": "not found"})
        if self.headers.get("If-None-Match") == entry["etag"]:
            self.send_response(304)
            self.send_header("ETag", entry["etag"])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return 304
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        body = entry["gz"] if gz else entry["raw"]
        self.send_response(200)
        self.send_header("Content-Type", entry["type"])
        self.send_header("ETag", entry["etag"])
        self.send_header("Cache-Control", "no-cache")
        if gz:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self._security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return 200

    def _authenticate(self, req):
        app = self.server.app
        authz = self.headers.get("Authorization") or ""
        if authz.lower().startswith("bearer "):
            dev = app.auth.device_for_token(authz[7:].strip(), req.ip)
            if dev:
                req.device, req.actor = dev, "device:%s" % dev["name"]
                return
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie") or "")
        except Exception:
            pass
        sid = cookie[SESSION_COOKIE].value if SESSION_COOKIE in cookie else None
        session = app.auth.sessions.get(sid)
        if session:
            req.session, req.session_id, req.actor = session, sid, "admin"

    def _dispatch(self, method):
        t0 = time.time()
        status = 500
        parts = urlsplit(self.path)
        path = parts.path
        req = None
        try:
            if method == "GET" and not path.startswith(("/api/", "/mcp")):
                status = self._static(path)
                return
            route, params = api.match(method, path)
            if route is None:
                raise HTTPError(404, "not found")
            req = Request(self, method, path, parse_qs(parts.query), params)
            self._authenticate(req)
            access = route["auth"]
            if access != "public":
                if req.actor is None:
                    raise HTTPError(401, "認証が必要です")
                if access == "admin" and req.actor != "admin":
                    raise HTTPError(403, "管理者のみ実行できます")
                if req.device and method != "GET" and req.device["scopes"] != "rw" and access != "read":
                    raise HTTPError(403, "読み取り専用デバイスです")
            if req.session and access != "public" and method not in ("GET", "HEAD"):
                origin = self.headers.get("Origin")
                if origin and origin != req.origin():
                    raise HTTPError(403, "Origin が一致しません")
                if self.headers.get("X-CSRF-Token") != req.session["csrf"]:
                    raise HTTPError(403, "CSRF トークンが不正です")
            result = route["fn"](req)
            if isinstance(result, int):
                status = result
            else:
                status = self.send_json(200, result)
        except HTTPError as error:
            status = self.send_json(error.status, dict({"error": error.message}, **error.extra))
        except (ValueError, KeyError, PermissionError) as error:
            status = self.send_json(403 if isinstance(error, PermissionError) else 400, {"error": str(error).strip("'")})
        except (BrokenPipeError, ConnectionResetError):
            status = 499
        except Exception as error:  # report, never leak a traceback to the client
            LOG.exception("unhandled error on %s %s", method, path)
            try:
                status = self.send_json(500, {"error": "内部エラー: %s" % type(error).__name__,
                                              "hint": "/api/debug/bundle の errors を確認してください"})
            except Exception:
                status = 500
        finally:
            debuglog.note_request(method, path, status, (time.time() - t0) * 1000, req.actor if req else None)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, addr, app, tls=None):
        family = socket.AF_INET6 if ":" in addr[0] else socket.AF_INET
        self.address_family = family
        super().__init__(addr, Handler)
        self.app = app
        self.tls = bool(tls)
        if tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(tls[0], tls[1])
            self.socket = ctx.wrap_socket(self.socket, server_side=True)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="qnaplibrary", description="QnapLibrary server")
    parser.add_argument("--data", default=os.environ.get("QNAPLIBRARY_DATA", "./.data"), help="persistent data directory")
    parser.add_argument("--bind", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--tls-cert", default=None)
    parser.add_argument("--tls-key", default=None)
    parser.add_argument("--log-level", default=os.environ.get("QNAPLIBRARY_LOG", "INFO"))
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print(VERSION)
        return 0
    debuglog.setup(args.log_level)
    app = App(args.data)
    cfg = app.config.get("server")
    bind = args.bind or os.environ.get("QNAPLIBRARY_BIND") or cfg.get("bind") or "0.0.0.0"
    port = args.port or int(os.environ.get("QNAPLIBRARY_PORT") or 0) or int(cfg.get("port") or DEFAULT_PORT)
    cert, key = args.tls_cert or cfg.get("tls_cert"), args.tls_key or cfg.get("tls_key")
    tls = (cert, key) if cert and key else None
    httpd = Server((bind, port), app, tls)
    app.httpd = httpd

    def stop(signum, _frame):
        app.request_shutdown(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    app.updater.start_background()
    app.embedder.start()
    app.embedder.kick()
    app.scheduler.start()
    LOG.warning("%s %s listening on %s://%s:%d (data: %s)", APP_NAME, VERSION, "https" if tls else "http", bind, port, args.data)
    try:
        httpd.serve_forever(poll_interval=1.0)
    finally:
        httpd.server_close()
        app.embedder.stop()
        app.scheduler.stop()
        app.store.close()
    return app.exit_code


if __name__ == "__main__":
    sys.exit(main())
