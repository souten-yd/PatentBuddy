import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path

from qnaplibrary.backup import BackupError, Backups
from qnaplibrary.store import Store
from tests.helpers import Client, LiveServer


class BackupStoreTest(unittest.TestCase):
    def test_snapshot_is_consistent_and_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "library.sqlite3")
            try:
                coll = store.create_collection("archive")
                store.add_documents(coll["id"], [{"id": "original", "title": "重要な文書", "body": "内容"}])
                backups = Backups(store)
                self.assertEqual(backups.list(), [])
                item = backups.create()
                path = Path(tmp) / item["path"]
                self.assertTrue(path.is_file())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                self.assertEqual(backups.list()[0]["name"], item["name"])
                self.assertFalse(list(path.parent.glob("*.partial")))
                with sqlite3.connect(str(path)) as db:
                    self.assertEqual(db.execute("PRAGMA quick_check").fetchone()[0], "ok")
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)
                store.add_documents(coll["id"], [{"id": "new", "title": "別文書", "body": "追加"}])
                with sqlite3.connect(str(path)) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)
            finally:
                store.close()

    def test_symlink_backup_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "library.sqlite3")
            try:
                outside = Path(tmp) / "outside"
                outside.mkdir()
                os.symlink(outside, Path(tmp) / "backups")
                backups = Backups(store)
                with self.assertRaises(BackupError):
                    backups.create()
                with self.assertRaises(BackupError):
                    backups.list()
                self.assertEqual(list(outside.iterdir()), [])
            finally:
                store.close()


class BackupApiTest(unittest.TestCase):
    def test_admin_csrf_and_mobile_icon(self):
        srv = LiveServer()
        try:
            anon = Client(srv.base)
            self.assertEqual(anon.call("GET", "/api/backups")[0], 401)
            self.assertEqual(anon.call("POST", "/api/backups", {})[0], 401)
            st, html = anon.call("GET", "/", raw=True)
            self.assertEqual(st, 200)
            self.assertIn(b"apple-touch-icon.png", html)
            st, png = anon.call("GET", "/apple-touch-icon.png", raw=True)
            self.assertEqual(st, 200)
            self.assertEqual(png[:8], bytes.fromhex("89504e470d0a1a0a"))
            self.assertEqual(int.from_bytes(png[16:20], "big"), 180)
            self.assertEqual(int.from_bytes(png[20:24], "big"), 180)
            admin = Client(srv.base)
            admin.login_setup()
            admin.csrf = None
            self.assertEqual(admin.call("POST", "/api/backups", {})[0], 403)
            st, login = admin.call("POST", "/api/auth/login", {"password": "correct-horse-1"})
            self.assertEqual(st, 200)
            admin.csrf = login["csrf"]
            self.assertEqual(admin.call("GET", "/api/backups")[1]["snapshots"], [])
            st, created = admin.call("POST", "/api/backups", {})
            self.assertEqual(st, 200, created)
            self.assertEqual(len(admin.call("GET", "/api/backups")[1]["snapshots"]), 1)
            self.assertTrue(Path(srv.tmp.name, created["snapshot"]["path"]).is_file())
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
