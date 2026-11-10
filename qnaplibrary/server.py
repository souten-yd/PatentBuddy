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
from .backup import Backups
from .config import Config
from .embedworker import EmbedWorker
from .notify import Notifier
from .research import Research
from .watch import Scheduler, Watches
from .llm import Providers
from .patents import Patents
from .public_catalog import PublicCatalog
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
    def __init__(self, data_dir, addon_mode=False):
        self.addon_mode = bool(addon_mode)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config = Config(self.data_dir)
        self.store = Store(self.data_dir / "library.sqlite3")
        self.public_catalog = PublicCatalog(self.store)
        self.backups = Backups(self.store)
        self.auth = Auth(self.config, self.store)
        self.providers = Providers(self.config)
        self._qdrant = None
        self.qdrant_sync = {"running": False, "done": 0, "error": None}
        self.searcher = Searcher(self.store, self.config, self._embedder, self._vector_model,
                                 backend_fn=self.qdrant, reranker=self.providers)
        self.store.on_vectors = self._mirror_vectors
        self.embedder = EmbedWorker(self.store, self.providers, self.config)
        self.store.on_change = self.embedder.kick
        self.notifier = Notifier(self.config, self.store)
        self.watches = Watches(self)
        self.scheduler = Scheduler(self)
        self.research = Research(self)
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

    def qdrant(self):
        """Qdrant client when vector_backend.type == 'qdrant', else None (RAM index)."""
        vb = self.config.get("vector_backend", default={}) or {}
        if vb.get("type") != "qdrant" or not vb.get("url"):
            self._qdrant = None
            return None
        # A remote Qdrant index would receive raw invention-derived embeddings.
        from .privacy import local_endpoint
        if not local_endpoint(vb["url"]):
            raise ValueError("機密保護: Qdrantの送信先はNAS内または明示許可されたHTTPS LANに限定されます")
        from .qdrant import Qdrant
        key = (vb["url"], vb.get("collection") or "qnaplibrary")
        if self._qdrant is None or (self._qdrant.url, self._qdrant.collection) != (key[0].rstrip("/"), key[1]):
            self._qdrant = Qdrant(key[0], key[1], self.config.secret("qdrant_api_key"))
        return self._qdrant

    def _mirror_vectors(self, rows):
        q = self.qdrant()
        if q is None or self.qdrant_sync["running"]:
            return
        try:
            q.upsert(rows)
        except Exception as error:  # SQLite keeps the vectors; a later sync repairs Qdrant
            LOG.warning("qdrant mirror failed: %s", error)

    def sync_qdrant(self, recreate=False):
        q = self.qdrant()
        if q is None:
            raise ValueError("vector_backend.type が qdrant ではありません")
        if self.qdrant_sync["running"]:
            raise ValueError("同期中です")

        def run():
            self.qdrant_sync.update(running=True, done=0, error=None)
            try:
                first = True
                for rows in self.store.iter_vectors():
                    if first:
                        q.ensure(len(rows[0][3]), recreate=recreate)
                        first = False
                    self.qdrant_sync["done"] += q.upsert(rows)
            except Exception as error:
                self.qdrant_sync["error"] = str(error)[:300]
            finally:
                self.qdrant_sync["running"] = False
        threading.Thread(target=run, daemon=True).start()
        return self.qdrant_sync

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
            "vector_backend": self.config.get("vector_backend"), "qdrant_sync": self.qdrant_sync,
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
            self.h._body_consumed = True
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
        self._body_consumed = False
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PUT, PATCH, DELETE")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def end_headers(self):
        # Unread bodies (including rejected requests) must never become the
        # next request line on an HTTP/1.1 connection. Do not drain untrusted
        # bodies: close explicitly so clients reconnect without a retry.
        headers = getattr(self, "headers", {})
        if (self.close_connection or headers.get("Transfer-Encoding") or
                (headers.get("Content-Length", "0") != "0" and
                 not getattr(self, "_body_consumed", False))):
            self.send_header("Connection", "close")
            self.close_connection = True
        super().end_headers()

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
        self._body_consumed = False
        t0 = time.time()
        status = 500
        parts = urlsplit(self.path)
        path = parts.path
        req = None
        try:
            if self.headers.get("Transfer-Encoding"):
                raise HTTPError(400, "Transfer-Encoding is not supported")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) > 1 or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit())):
                self.close_connection = True
                raise HTTPError(400, "Invalid Content-Length")
            if self.server.app.addon_mode:
                if method == "GET" and path == "/addon/v1/health":
                    from .addon import health_report
                    status = self.send_json(200, health_report())
                    return
                if method == "GET" and path in ("/addon/workspace", "/addon/style.css", "/addon/icon.svg"):
                    entry = {
                        "/addon/workspace": "/addon-workspace.html",
                        "/addon/style.css": "/style.css",
                        "/addon/icon.svg": "/icon.svg",
                    }[path]
                    status = self._static(entry)
                    return
                # The existing REST/MCP/auth endpoints are deliberately NOT
                # mapped to Host proxy principals in the A0 bootstrap slice.
                raise HTTPError(404, "addon endpoint not available")
            if path.startswith("/addon/"):
                raise HTTPError(404, "not found")

            if method == "GET" and not path.startswith(("/api/", "/mcp")):
                status = self._static(path)
                return
            route, params = api.match(method, path)
            if route is None:
                raise HTTPError(404, "not found")
            req = Request(self, method, path, parse_qs(parts.query), params)
            self._authenticate(req)
            access = route["auth"]
            # Published-only tokens may access ONLY the approved snapshot API.
            # Never treat them as ordinary read tokens that can inspect private
            # patent claims, drafts, settings, export, or the whole corpus.
            if req.device and req.device["scopes"] == "published":
                if access != "published":
                    raise HTTPError(403, "このトークンは公開済み資料の検索専用です")
                if not req.is_https() and req.ip not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                    raise HTTPError(403, "公開データ専用トークンはHTTPS接続が必要です")
            if access == "published" and req.actor != "admin" and (
                    not req.device or req.device["scopes"] != "published"):
                raise HTTPError(403, "公開資料専用の認証が必要です")
            if access != "public":
                if req.actor is None:
                    raise HTTPError(401, "認証が必要です")
                if access == "admin" and req.actor != "admin":
                    raise HTTPError(403, "管理者のみ実行できます")
                if req.device and method != "GET" and req.device["scopes"] != "rw" and access not in ("read", "published"):
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


class AddonShell:
    """Safe A0 ControlDeck shell. QNAP remains the only data authority.

    No local SQLite, secrets, user sessions, model client or jobs are started.
    Host identity and scoped NAS HTTPS API support arrive in A1/A2.
    """
    addon_mode = True
    exit_code = 0

    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.started = time.time()
        self.static = StaticCache(WEB_DIR)
        self.httpd = None

    def request_shutdown(self, exit_code=0):
        self.exit_code = exit_code
        if self.httpd:
            threading.Thread(target=self.httpd.shutdown, daemon=True).start()


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
    parser = argparse.ArgumentParser(prog="qnaplibrary", description="ResearchDataHub server / PatentBuddy Add-on")
    parser.add_argument("--data", default=None, help="persistent data directory")
    parser.add_argument("--addon", action="store_true", help="ControlDeck PatentBuddy loopback mode")
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
    if args.addon:
        data_dir = args.data or os.environ.get("PATENT_BUDDY_DATA_DIR")
        if not data_dir:
            parser.error("--addon requires --data or PATENT_BUDDY_DATA_DIR")
        bind = args.bind or "127.0.0.1"
        if bind not in ("127.0.0.1", "::1"):
            parser.error("--addon requires a loopback --bind")
        if args.tls_cert or args.tls_key:
            parser.error("--addon is loopback HTTP behind the ControlDeck TLS endpoint")
        port = args.port if args.port is not None else 9150
    else:
        data_dir = args.data or os.environ.get("QNAPLIBRARY_DATA", "./.data")
    debuglog.setup(args.log_level)
    app = AddonShell(data_dir) if args.addon else App(data_dir)
    if not args.addon:
        cfg = app.config.get("server")
        bind = args.bind or os.environ.get("QNAPLIBRARY_BIND") or cfg.get("bind") or "0.0.0.0"
        port = args.port or int(os.environ.get("QNAPLIBRARY_PORT") or 0) or int(cfg.get("port") or DEFAULT_PORT)
        cert, key = args.tls_cert or cfg.get("tls_cert"), args.tls_key or cfg.get("tls_key")
        tls = (cert, key) if cert and key else None
    else:
        tls = None
    httpd = Server((bind, port), app, tls)
    app.httpd = httpd

    def stop(signum, _frame):
        app.request_shutdown(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if not args.addon:
        app.updater.start_background()
        app.embedder.start()
        app.embedder.kick()
        app.scheduler.start()
    LOG.warning("%s %s listening on %s://%s:%d (data: %s)", APP_NAME, VERSION, "https" if tls else "http", bind, port, data_dir)
    try:
        httpd.serve_forever(poll_interval=1.0)
    finally:
        httpd.server_close()
        if not args.addon:
            app.embedder.stop()
            app.scheduler.stop()
        if not args.addon:
            app.store.close()
    return app.exit_code


if __name__ == "__main__":
    sys.exit(main())
