import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from qnaplibrary.auth import Auth, Sessions
from qnaplibrary.config import Config
from qnaplibrary.store import Store


class PersistentSessionsTest(unittest.TestCase):
    def test_restart_expiry_logout_and_no_get_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "test.sqlite3")
            store = Store(path)
            try:
                with mock.patch("qnaplibrary.auth.time.time", return_value=1000):
                    sid, session = Sessions(1, store).create("password")
                self.assertNotIn(sid, repr([tuple(r) for r in store.q("SELECT * FROM admin_sessions")]))
                self.assertEqual(store.one("SELECT sid_hash FROM admin_sessions")[0], hashlib.sha256(sid.encode()).hexdigest())
                store.close()
                store = Store(path)
                with mock.patch("qnaplibrary.auth.time.time", return_value=1001):
                    sessions = Sessions(1, store)
                    self.assertEqual(sessions.get(sid), session)
                    changes = store.db.total_changes
                    for _ in range(20):
                        self.assertIsNotNone(sessions.get(sid))
                    self.assertEqual(store.db.total_changes, changes)
                with mock.patch("qnaplibrary.auth.time.time", return_value=4600):
                    self.assertIsNone(sessions.get(sid))
                    self.assertEqual(store.db.total_changes, changes)
                sid, _ = sessions.create("passkey")
                sessions.drop(sid)
                self.assertIsNone(Sessions(1, store).get(sid))
            finally:
                store.close()

    def test_bound_and_password_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / "test.sqlite3"))
            try:
                auth = Auth(Config(tmp), store)
                auth.set_admin_password("old-password-test")
                first, _ = auth.sessions.create("password")
                for _ in range(Sessions.MAX_SESSIONS):
                    latest, _ = auth.sessions.create("password")
                self.assertIsNone(auth.sessions.get(first))
                self.assertEqual(store.one("SELECT COUNT(*) FROM admin_sessions")[0], Sessions.MAX_SESSIONS)
                self.assertIsNotNone(Sessions(store=store).get(latest))
                auth.set_admin_password("new-password-test")
                self.assertIsNone(Sessions(store=store).get(latest))
                self.assertEqual(store.one("SELECT COUNT(*) FROM admin_sessions")[0], 0)
            finally:
                store.close()

    def test_http_cookie_and_passkey_records_survive_restart(self):
        import contextlib
        import threading
        import time
        from qnaplibrary.server import App, Server
        from tests.helpers import Client

        with tempfile.TemporaryDirectory() as tmp:
            @contextlib.contextmanager
            def start():
                app = App(tmp)
                server = Server(("127.0.0.1", 0), app)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    yield app, "http://127.0.0.1:%d" % server.server_port
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                    app.store.close()
            with start() as (app, base):
                client = Client(base)
                client.login_setup()
                csrf = client.csrf
                app.store.db.execute(
                    "INSERT INTO passkeys(credential_id,public_key,alg,sign_count,name,created) VALUES(?,?,?,?,?,?)",
                    (b"synthetic-credential", b"synthetic-public-key", -7, 0, "fixture", time.time()))
                app.config.set_secret("passkey_user_handle", "synthetic-stable-handle")
            with start() as (app, base):
                client.base = base
                status, me = client.call("GET", "/api/auth/me")
                self.assertEqual(status, 200)
                self.assertTrue(me["authenticated"])
                self.assertEqual(me["csrf"], csrf)
                self.assertEqual(me["passkeys"], 1)
                status, options = client.call("POST", "/api/auth/passkey/login/options", {},
                    {"Host": "nas.example.test:8443", "Origin": "https://nas.example.test:8443",
                     "X-Forwarded-Proto": "https"})
                self.assertEqual(status, 200)
                self.assertEqual(options["publicKey"]["rpId"], "nas.example.test")
                self.assertEqual(len(options["publicKey"]["allowCredentials"]), 1)
                self.assertEqual(app.config.secret("passkey_user_handle"), "synthetic-stable-handle")
                self.assertEqual(client.call("POST", "/api/auth/logout", {})[0], 200)
            with start() as (app, base):
                client.base = base
                self.assertFalse(client.call("GET", "/api/auth/me")[1]["authenticated"])
