"""A0 Add-on v2 contract and fail-closed runtime regression checks."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from qnaplibrary.addon import health_report
from qnaplibrary import server
from tests.helpers import LiveServer, Client


ROOT = Path(__file__).resolve().parents[1]


class AddonManifestTest(unittest.TestCase):
    def test_declarative_v2_contract_has_no_unimplemented_capabilities(self):
        value = json.loads((ROOT / "addon.json").read_text(encoding="utf-8"))
        self.assertEqual(value["api_version"], "2")
        self.assertEqual(value["id"], "patent-buddy")
        self.assertEqual(value["requires"]["addon_contract"], ">=2.0 <3.0")
        self.assertEqual(value["runtime"]["base_url"], "http://127.0.0.1:9150")
        self.assertEqual(value["runtime"]["health_path"], "/addon/v1/health")
        self.assertEqual(value["host_capabilities"], ["context.read", "theme.read", "route.open", "ai.inference", "jobs.write"])
        view = value["contributions"]["embedded_views"][0]
        self.assertEqual(view["path"], "/addon/workspace")
        self.assertEqual(view["mobile"], "embedded")
        self.assertEqual(value["contributions"]["agent_tools"], [])
        self.assertEqual(value["contributions"]["workflow_executors"], [])

    def test_setup_remains_explicit(self):
        response = health_report()
        self.assertEqual(response["contract_version"], "2.0")
        self.assertEqual(response["status"], "setup_required")
        self.assertEqual(response["reason_code"], "setup_incomplete")
        self.assertEqual(response["setup"][0]["state"], "missing")


class AddonModeTest(unittest.TestCase):
    def test_addon_mode_exposes_only_safe_health_and_static_landing(self):
        srv = LiveServer()
        try:
            srv.app.addon_mode = True
            anon = Client(srv.base)
            status, health = anon.call("GET", "/addon/v1/health")
            self.assertEqual(status, 200)
            self.assertEqual(health["status"], "setup_required")
            status, page = anon.call("GET", "/addon/workspace", raw=True)
            self.assertEqual(status, 200)
            self.assertIn(b"PatentBuddy", page)
            self.assertNotIn(b"ql_session", page)
            with anon.opener.open(srv.base + "/addon/workspace") as response:
                self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
                self.assertIn("frame-ancestors 'self'", response.headers["Content-Security-Policy"])
            self.assertEqual(anon.call("GET", "/addon/style.css", raw=True)[0], 200)
            self.assertEqual(anon.call("GET", "/addon/icon.svg", raw=True)[0], 200)
            for method, path, body in (
                ("GET", "/api/health", None),
                ("GET", "/api/v1/stats", None),
                ("POST", "/api/auth/setup", {"password": "set-admin-secret"}),
                ("POST", "/api/v1/collections", {"name": "unexpected"}),
                ("GET", "/addon-workspace.html", None),
                ("POST", "/addon/v1/health", {}),
            ):
                status, _ = anon.call(method, path, body)
                self.assertEqual(status, 404, (method, path))
            self.assertFalse(srv.app.auth.admin_configured())
        finally:
            srv.close()

    def test_legacy_mode_does_not_publish_addon_health(self):
        srv = LiveServer()
        try:
            anon = Client(srv.base)
            self.assertEqual(anon.call("GET", "/addon/v1/health")[0], 404)
            self.assertEqual(anon.call("GET", "/api/health")[0], 200)
        finally:
            srv.close()

    def test_addon_mode_rejects_non_loopback_and_missing_data_directory(self):
        with self.assertRaises(SystemExit) as failure:
            server.main(["--addon", "--data", "some-local-path", "--bind", "0.0.0.0"])
        self.assertEqual(failure.exception.code, 2)
        with patch.dict("os.environ", {"PATENT_BUDDY_DATA_DIR": ""}):
            with self.assertRaises(SystemExit) as failure:
                server.main(["--addon"])
        self.assertEqual(failure.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
