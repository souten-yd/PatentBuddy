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
