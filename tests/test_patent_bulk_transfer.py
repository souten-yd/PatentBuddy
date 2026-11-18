"""Explicit USPTO ODP bulk ZIP staging; isolated fake HTTP, no upstream key."""
import fcntl
import hashlib
import io
import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qnaplibrary import patent_bulk_transfer as bulk
from tests.helpers import Client, LiveServer


def tiny_zip():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("patents.xml", "<patent><id>US123</id></patent>")
    return stream.getvalue()


class FakeResponse:
    def __init__(self, payload, *, status=200, length=None, etag='"test-version"',
                 start=None, total=None, on_read=None):
        self.payload = io.BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload) if length is None else length)}
        if etag is not None:
            self.headers["ETag"] = etag
        if start is not None:
            self.headers["Content-Range"] = "bytes %d-%d/%d" % (
                start, start + len(payload) - 1, total)
        self.status = status
        self.on_read = on_read

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if self.on_read is not None:
            callback, self.on_read = self.on_read, None
            callback()
        return self.payload.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, req, timeout=30):
        self.requests.append(req)
        if not self.responses:
            raise AssertionError("unexpected external download")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ManualBulkFileUnitTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.manager = bulk.ManualBulkTransfer(Path(self.scratch.name))
        self.zip = tiny_zip()
        self.product = "PTGRXML"
        self.name = "ipg260101.zip"

    def fake_download(self, opener, *, restart=False):
        with patch.object(bulk.urllib.request, "build_opener", return_value=opener):
            self.manager._download(self.product, self.name, len(self.zip), "not-a-real-key", restart)

    def test_download_sha256_and_no_public_storage_url(self):
        opener = FakeOpener([FakeResponse(self.zip)])
        self.fake_download(opener)
        result = self.manager.status(self.product, self.name)
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["bytes_done"], len(self.zip))
        self.assertEqual(result["sha256"], hashlib.sha256(self.zip).hexdigest())
        self.assertTrue(result["file_not_publicly_served"])
        path = Path(self.scratch.name) / "bulk_staging" / self.product / self.name
        self.assertEqual(path.read_bytes(), self.zip)
        self.assertFalse(path.with_suffix(".zip.part").exists())
        req = opener.requests[0]
        self.assertEqual(req.full_url,
            "https://api.uspto.gov/api/v1/datasets/products/files/PTGRXML/ipg260101.zip")
        self.assertIn("X-api-key", req.headers)
        self.assertNotIn("not-a-real-key", req.full_url)
        self.assertNotIn("not-a-real-key", str(result))

    def test_interruption_only_resumes_with_strong_etag_and_exact_range(self):
        first = self.zip[:40]
        opener = FakeOpener([
            FakeResponse(first, length=len(self.zip)),
            FakeResponse(self.zip[len(first):], status=206,
                         start=len(first), total=len(self.zip))
        ])
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(opener)
        progress = self.manager.status(self.product, self.name)
        self.assertEqual(progress["state"], "interrupted")
        self.assertEqual(progress["bytes_done"], len(first))
        self.assertTrue(progress["can_resume"])
        self.fake_download(opener)
        self.assertEqual(self.manager.status(self.product, self.name)["state"], "completed")
        resumed = opener.requests[1]
        self.assertEqual(resumed.headers.get("Range"), "bytes=40-")
        self.assertEqual(resumed.headers.get("If-range"), '"test-version"')

    def test_if_range_server_ignores_range_never_appends(self):
        first = self.zip[:32]
        opener = FakeOpener([FakeResponse(first, length=len(self.zip)),
                             FakeResponse(self.zip)])  # 200 instead of 206
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(opener)
        before = self.manager.status(self.product, self.name)["bytes_done"]
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(opener)
        self.assertEqual(self.manager.status(self.product, self.name)["bytes_done"], before)

    def test_mismatched_etag_and_content_range_never_appends(self):
        first = self.zip[:32]
        opener = FakeOpener([
            FakeResponse(first, length=len(self.zip)),
            FakeResponse(self.zip[32:], status=206, etag='"another"',
                         start=32, total=len(self.zip)),
            FakeResponse(self.zip[32:], status=206, start=31, total=len(self.zip))
        ])
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(opener)
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(opener)
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(opener)
        self.assertEqual(self.manager.status(self.product, self.name)["bytes_done"], 32)

    def test_cancelled_stream_is_preserved_without_auto_restart(self):
        opener = FakeOpener([FakeResponse(self.zip, on_read=self.manager._cancel.set)])
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(opener)
        self.assertTrue(self.manager._cancel.is_set())
        self.assertEqual(self.manager.status(self.product, self.name)["state"], "interrupted")
        self.assertFalse((Path(self.scratch.name) / "bulk_staging" /
                          self.product / self.name).exists())

    def test_redirect_html_body_malformed_length_and_bad_file_denied(self):
        for response in (
            FakeResponse(b"not-a-zip", length=9),
            FakeResponse(self.zip, length=99999),
            FakeResponse(self.zip, status=206, start=0, total=len(self.zip)),
            urllib.error.HTTPError("https://api.uspto.gov", 302, "redirect",
                                   {"Location": "https://evil.example/"}, None),
        ):
            with self.subTest(response=response):
                with self.assertRaises(bulk.BulkTransferError):
                    self.fake_download(FakeOpener([response]), restart=True)
                self.assertFalse((Path(self.scratch.name) / "bulk_staging" /
                                  self.product / self.name).exists())
        for bad in ("../evil.zip", "http://a.zip", "x.txt", "%2F.zip", ".zip", "dir/x.zip"):
            with self.subTest(name=bad), self.assertRaises(bulk.BulkTransferError):
                bulk._api_url("PTGRXML", bad)
        with self.assertRaises(bulk.BulkTransferError):
            bulk._api_url("UNLISTED", self.name)

    def test_file_bytes_cap_free_space_and_symlinks(self):
        manager = self.manager
        with self.assertRaises(bulk.BulkTransferError):
            manager.start(product=self.product, name=self.name,
                          expected_bytes=bulk.MAX_FILE_BYTES + 1,
                          key="unit-key", source_lock=threading.Lock())
        with patch.object(bulk.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
            with self.assertRaises(bulk.BulkTransferError):
                self.fake_download(FakeOpener([]))
        root = Path(self.scratch.name) / "some-directory"
        root.mkdir()
        target = Path(self.scratch.name) / "bulk_staging"
        shutil.rmtree(target)
        target.symlink_to(root, target_is_directory=True)
        with self.assertRaises(bulk.BulkTransferError):
            self.fake_download(FakeOpener([]))

    def test_hard_total_staging_cap_without_network(self):
        opener = FakeOpener([])
        with patch.object(self.manager, "_staging_used",
                          return_value=bulk.MAX_STAGING_BYTES):
            with self.assertRaisesRegex(bulk.BulkTransferError, "2GiB"):
                self.fake_download(opener)
        self.assertEqual(opener.requests, [])
        self.assertFalse((Path(self.scratch.name) / "bulk_staging" /
                          self.product / self.name).exists())

    def test_process_lock_prevents_a_second_writer(self):
        root = Path(self.scratch.name) / "bulk_staging"
        root.mkdir(mode=0o700)
        locked_file = root / ".manual-transfer.lock"
        opener = FakeOpener([])
        with locked_file.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaisesRegex(bulk.BulkTransferError, "別プロセス"):
                    self.fake_download(opener)
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
        self.assertFalse(opener.requests)

    def test_idle_constructor_does_not_create_staging_directory(self):
        self.assertFalse((Path(self.scratch.name) / "bulk_staging").exists())
        self.assertEqual(self.manager.status()["state"], "idle")
        self.assertFalse((Path(self.scratch.name) / "bulk_staging").exists())

    def test_async_manual_one_file_and_existing_hash_idempotency(self):
        opener = FakeOpener([FakeResponse(self.zip)])
        source_lock = threading.Lock()
        self.assertTrue(source_lock.acquire(blocking=False))
        with patch.object(bulk.urllib.request, "build_opener", return_value=opener):
            result = self.manager.start(product=self.product, name=self.name,
                expected_bytes=len(self.zip), key="unit-key",
                source_lock=source_lock)
            self.assertEqual(result["state"], "running")
            self.manager._thread.join(timeout=5)
        self.assertFalse(self.manager._thread.is_alive())
        self.assertEqual(self.manager.status(self.product, self.name)["state"], "completed")
        self.assertTrue(source_lock.acquire(blocking=False))
        source_lock.release()
        self.fake_download(FakeOpener([]))
        self.assertEqual(self.manager.status(self.product, self.name)["state"], "completed")
        # Explicit admin restart is required to discard a staged completed file.
        self.fake_download(FakeOpener([FakeResponse(self.zip)]), restart=True)


class ManualBulkHTTPAuthTests(unittest.TestCase):
    def test_admin_only_recheck_official_file_size_then_start(self):
        server = LiveServer()
        try:
            admin = Client(server.base); admin.login_setup()
            reader = Client(server.base); reader.token = server.app.auth.local_token()
            anon = Client(server.base)
            req = {"product": "PTGRXML", "file_name": "ipg260101.zip",
                   "expected_bytes": len(tiny_zip()), "confirmed": True}
            self.assertEqual(anon.call("POST", "/api/v1/uspto-bulk/transfer/start", req)[0], 401)
            self.assertEqual(reader.call("POST", "/api/v1/uspto-bulk/transfer/start", req)[0], 403)
            self.assertEqual(admin.call("POST", "/api/v1/uspto-bulk/transfer/start",
                dict(req, confirmed=False))[0], 400)
            self.assertEqual(admin.call("POST", "/api/v1/uspto-bulk/transfer/start",
                dict(req, url="https://malicious.example"))[0], 400)
            self.assertEqual(admin.call("POST", "/api/v1/uspto-bulk/transfer/start", req)[0], 400)
            server.app.config.set_secret("uspto_api_key", "test-key")
            match = {"files": [{"file_name": req["file_name"], "bytes": req["expected_bytes"]}]}
            with patch("qnaplibrary.patent_bulk_catalog.preview", return_value=match) as catalog:
                with patch.object(bulk.urllib.request, "build_opener",
                                  return_value=FakeOpener([FakeResponse(tiny_zip())])):
                    code, result = admin.call("POST", "/api/v1/uspto-bulk/transfer/start",
                                               dict(req, expected_bytes=len(tiny_zip())+1))
                    self.assertEqual(code, 409, result)
                    code, result = admin.call("POST", "/api/v1/uspto-bulk/transfer/start", req)
                    self.assertEqual(code, 200, result)
                    server.app.uspto_bulk_transfer._thread.join(timeout=5)
            self.assertEqual(catalog.call_args.kwargs["limit"], 10)
            code, progress = reader.call("GET",
                "/api/v1/uspto-bulk/transfer/status?product=PTGRXML&file_name=ipg260101.zip")
            self.assertEqual(code, 200, progress)
            self.assertEqual(progress["state"], "completed")
            self.assertNotIn("path", progress)
            self.assertNotIn("key", progress)
            self.assertEqual(admin.call("POST", "/api/v1/uspto-bulk/transfer/cancel",
                {"product":"PTGRXML","file_name":"ipg260101.zip","confirmed":True})[0], 409)
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
