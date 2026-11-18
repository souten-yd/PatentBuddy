"""K7a: scoped retrieval is opt-in and bounded; figures are only candidates."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from qnaplibrary import source_planner, source_storage, pdf_figure_regions
from qnaplibrary.store import Store
from tests.helpers import Client, LiveServer


class SourcePlannerTests(unittest.TestCase):
    def test_technical_scope_preview_offline(self):
        for keyword, expected in (("インバータ", "H02M"), ("電気", "H02J"), ("機械", "F16H"),
                                  ("inverter", "H02P")):
            result = source_planner.plan(keyword)
            self.assertIn(expected, [item["code"] for item in result["candidates"]])
            self.assertTrue(result["preview_only"])
            self.assertTrue(all(item["cql_preview"] == "ic=" + item["code"]
                                for item in result["candidates"]))
        self.assertEqual(source_planner.plan("unknown-topic")["candidates"], [])
        for value in ("", "a" * 121, "x\nsecret", None):
            with self.assertRaises(ValueError):
                source_planner.plan(value)
        for value in ("H02M or ta=secret", "H02M*", "h02m"):
            with self.assertRaises(ValueError):
                source_planner.accepted_ipc(value)

    def test_source_policy_usage_and_zero_write(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "main.sqlite3")
            try:
                base = source_storage.usage(store, include_counts=True)
                self.assertGreater(base["files"]["sqlite_bytes"], 0)
                self.assertEqual(base["counts"]["documents"], 0)
                self.assertEqual(base["counts"]["pdf_originals"], 0)
                old = store.db.total_changes
                source_storage.usage(store, include_counts=True)
                self.assertEqual(store.db.total_changes, old)
                custom = dict(source_storage.DEFAULT_POLICY, soft_limit_mib=1024)
                self.assertEqual(source_storage.save_policy(store, custom)["soft_limit_mib"], 1024)
                self.assertEqual(source_storage.policy(store)["soft_limit_mib"], 1024)
                for updates in ({"soft_limit_mib": 0}, {"max_results_per_fetch": 50},
                                {"allow_scheduled_collection": True}, {"max_figures_per_pdf": -1}):
                    with self.assertRaises(ValueError):
                        source_storage.save_policy(store, dict(custom, **updates))
            finally:
                store.close()

    def test_http_scope_and_one_shot_privacy(self):
        server = LiveServer()
        try:
            admin = Client(server.base)
            admin.login_setup()
            read = Client(server.base)
            read.token = server.app.auth.local_token()
            noauth = Client(server.base)
            self.assertEqual(noauth.call("POST", "/api/v1/source-plan", {"topic": "インバータ"})[0], 401)
            code, result = read.call("POST", "/api/v1/source-plan", {"topic": "インバータ"})
            self.assertEqual(code, 200, result)
            self.assertEqual(result["candidates"][0]["code"], "H02M")
            self.assertEqual(read.call("GET", "/api/v1/source-storage")[0], 200)
            self.assertEqual(read.call("PUT", "/api/v1/source-storage/policy", source_storage.DEFAULT_POLICY)[0], 403)
            self.assertEqual(read.call("POST", "/api/v1/source-acquisitions",
                                       {"ipc": "H02M", "limit": 1, "public_only_confirmed": True})[0], 403)
            self.assertEqual(admin.call("POST", "/api/v1/source-acquisitions",
                                        {"ipc": "H02M", "limit": 1, "public_only_confirmed": False})[0], 400)
            with patch("qnaplibrary.connectors.epo_search", return_value=[
                {"id": "EP123456", "title": "Sample", "source": "EPO OPS"}]) as download:
                code, result = admin.call("POST", "/api/v1/source-acquisitions",
                                          {"ipc": "H02M", "limit": 1, "public_only_confirmed": True})
                self.assertEqual(code, 200, result)
                self.assertEqual(result["received"], 1)
                self.assertEqual(download.call_args.args[0], "ic=H02M")
                self.assertEqual(download.call_args.args[-1], 1)
        finally:
            server.close()


class PDFRegionTests(unittest.TestCase):
    def test_crop_geometry_and_image_candidate(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("Optional PC PyMuPDF not installed")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "sample.pdf"
            doc = fitz.open()
            page = doc.new_page(width=600, height=800)
            page.draw_rect(fitz.Rect(100, 120, 340, 350))
            page.insert_text((105, 110), "FIG. 1")
            doc.save(str(path))
            doc.close()
            scan = pdf_figure_regions.scan(path)
            self.assertEqual(scan["page_count"], 1)
            self.assertTrue(scan["candidates"])
            self.assertTrue(all(item["status"] == "unreviewed" for item in scan["candidates"]))
            candidate = scan["candidates"][0]
            image = pdf_figure_regions.crop(path, page_number=1,
                                            bbox_points=candidate["bbox_points"], dpi=120)
            self.assertTrue(image["png"].startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(image["sha256"], __import__("hashlib").sha256(image["png"]).hexdigest())
            self.assertLess(image["size_bytes"], 2 * 1024 * 1024)
            for box in ((-1, 0, 100, 100), (0, 0, 700, 700), (0, 0, 1, 1),
                        (float("nan"), 0, 100, 100)):
                with self.assertRaises(ValueError):
                    pdf_figure_regions.crop(path, page_number=1, bbox_points=box)
            with self.assertRaises(ValueError):
                pdf_figure_regions.scan(path, limit_pages=0)



class SourceHistoryTests(unittest.TestCase):
    def test_source_receipts_and_metadata_only_samples(self):
        from qnaplibrary import source_history
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "main.sqlite3")
            try:
                coll = store.ensure_collection("patent-usage", "patent")
                store.add_documents(coll["id"], [
                    {"id": "EP1", "title": "実験A", "body": "実験結果", "source": "EPO OPS"},
                    {"id": "EP2", "title": "実験B", "body": "制御回路", "source": "EPO OPS"},
                    {"id": "JP1", "title": "機械", "body": "歯車", "source": "JPO bulk"},
                ])
                old = store.db.total_changes
                sample = source_history.by_source_sample(store, limit=2)
                self.assertEqual(store.db.total_changes, old)
                self.assertTrue(sample["has_older_documents"])
                self.assertTrue(sample["not_physical_storage"])
                self.assertEqual(sample["documents_examined"], 2)
                self.assertGreater(sum(x["logical_payload_bytes_in_sample"] for x in sample["items"]), 0)
                for size in (0, 5001, True):
                    with self.assertRaises(ValueError):
                        source_history.by_source_sample(store, size)
                started = source_history.start(store, "epo_ops", "H02M", 2)
                self.assertEqual(source_history.list_recent(store)[0]["status"], "running")
                source_history.finish(store, started, "succeeded",
                                      received=2, added=1, response_bytes=125)
                row = source_history.list_recent(store)[0]
                self.assertEqual((row["status"], row["received"], row["added"], row["response_bytes"]),
                                 ("succeeded", 2, 1, 125))
                with self.assertRaises(ValueError):
                    source_history.finish(store, started, "succeeded")
                with self.assertRaises(ValueError):
                    source_history.list_recent(store, 51)
                self.assertEqual(store.one("SELECT count(*) FROM source_acquisition_runs")[0], 1)
            finally:
                store.close()

    def test_manual_http_receipts_error_safety_and_double_start(self):
        from qnaplibrary.connectors import ConnectorError
        server = LiveServer()
        try:
            admin = Client(server.base); admin.login_setup()
            ro = Client(server.base); ro.token = server.app.auth.local_token()
            anon = Client(server.base)
            self.assertEqual(anon.call("GET", "/api/v1/source-acquisitions")[0], 401)
            self.assertEqual(ro.call("GET", "/api/v1/source-acquisitions")[0], 200)
            self.assertEqual(ro.call("GET", "/api/v1/source-storage?breakdown=1")[0], 200)
            self.assertEqual(ro.call("GET", "/api/v1/source-storage?breakdown=bad")[0], 400)
            payload = {"ipc": "H02M", "limit": 1, "public_only_confirmed": True}
            self.assertTrue(server.app.source_fetch_lock.acquire(blocking=False))
            try:
                self.assertEqual(admin.call("POST", "/api/v1/source-acquisitions", payload)[0], 429)
            finally:
                server.app.source_fetch_lock.release()
            with patch("qnaplibrary.connectors.epo_search",
                       side_effect=ConnectorError("secret=must_not_echo")):
                code, result = admin.call("POST", "/api/v1/source-acquisitions", payload)
                self.assertEqual(code, 502, result)
                self.assertNotIn("must_not_echo", str(result))
            code, result = ro.call("GET", "/api/v1/source-acquisitions")
            self.assertEqual(code, 200, result)
            self.assertEqual(result["items"][0]["status"], "failed")
            self.assertEqual(result["items"][0]["failure_code"], "provider_error")
            with patch("qnaplibrary.connectors.epo_search", return_value=[
                {"id": "EP1", "title": "Sample 1", "source": "EPO OPS"},
                {"id": "EP2", "title": "Sample 2", "source": "EPO OPS"},
            ]):
                self.assertEqual(admin.call("POST", "/api/v1/source-acquisitions", payload)[0], 413)
            self.assertEqual(ro.call("GET", "/api/v1/source-acquisitions")[1]["items"][0]["failure_code"],
                             "limit_error")
            with patch("qnaplibrary.connectors.epo_search", return_value=[
                {"id": "EP3", "title": "Sample 3", "source": "EPO OPS"},
            ]):
                code, result = admin.call("POST", "/api/v1/source-acquisitions", payload)
                self.assertEqual(code, 200, result)
                self.assertEqual(result["received"], 1)
                self.assertIsInstance(result["receipt_id"], int)
            last = ro.call("GET", "/api/v1/source-acquisitions")[1]["items"][0]
            self.assertEqual(last["status"], "succeeded")
            self.assertEqual((last["received"], last["added"]), (1, 1))
        finally:
            server.close()

    def test_pdf_region_provenance_validation_does_not_approve(self):
        from qnaplibrary import pdf_store
        from tests.test_pdf_images import value, png
        payload = value()
        item = payload["images"][0]
        item.update(kind="figure_candidate", method="local_pdf_page_crop",
                    bbox_points=[10.0, 15.0, 150.0, 215.0])
        self.assertEqual(len(pdf_store.validate_images(payload, {0: png()})), 1)
        self.assertEqual(item["review_status"], "unreviewed")
        for coords in ([0, 0, 1, 1], [-1, 0, 30, 30],
                       [float("nan"), 10, 50, 50], ["foo", 0, 60, 60]):
            item["bbox_points"] = coords
            with self.assertRaises(ValueError):
                pdf_store.validate_images(payload, {0: png()})



class PDFIsolatedWorkerTests(unittest.TestCase):
    def test_sandboxed_worker_png_crop_and_no_disk_staging_leaks(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("Optional local PC PyMuPDF not installed")
        import threading
        from qnaplibrary import pdf_extract
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            images = root / "images"
            images.mkdir()
            path = root / "sample.pdf"
            pdf = fitz.open()
            page = pdf.new_page(width=600, height=800)
            page.draw_rect(fitz.Rect(100, 150, 340, 400))
            pdf.save(str(path))
            pdf.close()
            preview, crops = pdf_extract._geometry_candidates(
                path, images, start_index=0, limit=2, cancel=threading.Event())
            self.assertEqual(preview["status"], "unreviewed", preview)
            self.assertTrue(crops)
            self.assertEqual(crops[0]["method"], "local_pdf_page_crop")
            self.assertTrue((images / "0.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertFalse((images / "figure-worker-report.json").exists())
            canceled = threading.Event()
            canceled.set()
            with self.assertRaises(pdf_extract.PDFError):
                pdf_extract._geometry_candidates(path, images, 2, 1, canceled)
            self.assertFalse((images / "2.png").exists())
            self.assertFalse((images / "figure-worker-report.json").exists())
