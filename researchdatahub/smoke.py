"""Offline distribution acceptance; uses disposable data and real HTTP processes."""
import contextlib
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from qnaplibrary.config import Config


class EntrySmoke(unittest.TestCase):
    @contextlib.contextmanager
    def server(self, module, data):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        root = str(Path(__file__).resolve().parent.parent)
        env = dict(os.environ, PYTHONPATH=root)
        with tempfile.TemporaryFile() as log:
            proc = subprocess.Popen([sys.executable, "-B", "-m", module, "--data", str(data),
                                     "--bind", "127.0.0.1", "--port", str(port)],
                                    cwd=root, env=env, stdout=log, stderr=log)
            try:
                self.base = "http://127.0.0.1:%d" % port
                self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                self.csrf = None
                for _ in range(100):
                    if proc.poll() is not None:
                        self.fail("server exited before becoming healthy")
                    try:
                        self.call("GET", "/api/health")
                        break
                    except (urllib.error.URLError, OSError):
                        time.sleep(0.05)
                else:
                    self.fail("server did not become healthy")
                yield
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

    def call(self, method, path, body=None, headers=None):
        h = {"Content-Type": "application/json"}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, method=method, headers=h,
            data=json.dumps(body).encode() if body is not None else None)
        with self.opener.open(req, timeout=2) as response:
            return json.load(response)

    def test_old_and_new_entry_share_only_explicit_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            shared = Path(tmp) / "shared"
            separate = Path(tmp) / "separate"
            for data in (shared, separate):
                Config(data).update({"update": {"auto_check": False}})
            for module, setup in (("qnaplibrary", True), ("researchdatahub", False)):
                with self.server(module, shared):
                    health = self.call("GET", "/api/health")
                    self.assertEqual(health["app"], "ResearchDataHub")
                    self.assertEqual(health["setup_required"], setup)
                    auth = self.call("POST", "/api/auth/" + ("setup" if setup else "login"),
                                     {"password": "disposable-smoke-password"})
                    self.csrf = auth["csrf"]
                    if setup:
                        self.call("POST", "/api/v1/collections", {"name": "persistent"})
                    else:
                        self.assertIn("persistent", json.dumps(self.call("GET", "/api/v1/collections")))
                    options = self.call("POST", "/api/auth/passkey/register/options", {},
                        {"Host": "nas.example.test:8443", "Origin": "https://nas.example.test:8443",
                         "X-Forwarded-Proto": "https"})
                    self.assertEqual(options["publicKey"]["rp"]["id"], "nas.example.test")
            with self.server("researchdatahub", separate):
                self.assertTrue(self.call("GET", "/api/health")["setup_required"])

    def test_missing_data_does_not_initialize(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            env.pop("QNAPLIBRARY_DATA", None)
            result = subprocess.run([sys.executable, "-B", "-m", "researchdatahub"],
                                    cwd=tmp, env=env, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_doctor_has_no_persistent_side_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
            result = subprocess.run([sys.executable, "-B", "-m", "researchdatahub.cli", "doctor"],
                                    cwd=tmp, env=env, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout)["app"], "ResearchDataHub")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_shell_entry_ignores_other_checkout_in_cwd(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "researchdatahub"
            fake.mkdir()
            (fake / "__init__.py").write_text("raise RuntimeError('wrong checkout')")
            result = subprocess.run([str(root / "rdh.sh"), "doctor"], cwd=tmp,
                                    capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout)["app"], "ResearchDataHub")
