import http.cookiejar
import json
import tempfile
import threading
import urllib.error
import urllib.request

from qnaplibrary import debuglog
from qnaplibrary.server import App, Server


class LiveServer:
    """Start the real HTTP server on a random port in a thread."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        debuglog.setup("WARNING", stderr=False)
        self.app = App(self.tmp.name)
        self.httpd = Server(("127.0.0.1", 0), self.app)
        self.app.httpd = self.httpd
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.app.store.close()
        self.tmp.cleanup()


class Client:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = None
        self.token = None

    def call(self, method, path, body=None, headers=None, raw=False):
        h = {"Content-Type": "application/json"}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        h.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=20) as resp:
                content = resp.read()
                return resp.status, (content if raw else (json.loads(content) if content else None))
        except urllib.error.HTTPError as error:
            content = error.read()
            try:
                return error.code, json.loads(content)
            except ValueError:
                return error.code, content

    def login_setup(self, password="correct-horse-1"):
        status, body = self.call("POST", "/api/auth/setup", {"password": password})
        assert status == 200, body
        self.csrf = body["csrf"]
        return body
