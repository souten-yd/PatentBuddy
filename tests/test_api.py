import json
import unittest
from unittest import mock

from tests.helpers import Client, LiveServer


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = LiveServer()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def setUp(self):
        self.c = Client(self.srv.base)
        if self.srv.app.auth.admin_configured():
            st, body = self.c.call("POST", "/api/auth/login", {"password": "correct-horse-1"})
            self.assertEqual(st, 200)
            self.c.csrf = body["csrf"]
        else:
            self.c.login_setup()

    def test_01_health_public_and_static(self):
        anon = Client(self.srv.base)
        st, body = anon.call("GET", "/api/health")
        self.assertEqual(st, 200)
        self.assertIn("version", body)
        st, _ = anon.call("GET", "/api/v1/collections")
        self.assertEqual(st, 401)
        st, raw = anon.call("GET", "/", raw=True)
        self.assertEqual(st, 200)
        self.assertIn(b"app.js", raw)

    def test_02_csrf_required(self):
        self.c.csrf = None
        st, body = self.c.call("POST", "/api/v1/collections", {"name": "x"})
        self.assertEqual(st, 403)

    def test_03_setup_only_once_and_bad_login(self):
        anon = Client(self.srv.base)
        self.assertEqual(anon.call("POST", "/api/auth/setup", {"password": "another-pass-1"})[0], 409)
        self.assertEqual(anon.call("POST", "/api/auth/login", {"password": "wrong"})[0], 401)

    def test_04_documents_search_export(self):
        st, coll = self.c.call("POST", "/api/v1/collections", {"name": "news", "kind": "news"})
        self.assertEqual(st, 200, coll)
        st, r = self.c.call("POST", "/api/v1/collections/news/import",
                            {"format": "csv", "data": "id,title,body,country\n1,輸出規制の強化,半導体製造装置の輸出規制,JP\n2,市場動向,電池市場が拡大,US\n"})
        self.assertEqual(r["added"], 2)
        st, r = self.c.call("POST", "/api/v1/search", {"q": "輸出規制", "collections": ["news"]})
        self.assertEqual(r["results"][0]["ext_id"], "1")
        self.assertNotIn("text", r["results"][0])
        st, raw = self.c.call("GET", "/api/v1/collections/news/export", raw=True)
        lines = raw.decode().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["meta"]["country"], "JP")

    def test_05_pairing_device_token_and_scopes(self):
        anon = Client(self.srv.base)
        self.assertEqual(anon.call("POST", "/api/v1/pair", {"passcode": "x"})[0], 409)
        self.assertEqual(self.c.call("PUT", "/api/devices/pairing", {"passcode": "lan-secret-9"})[0], 200)
        self.assertEqual(anon.call("POST", "/api/v1/pair", {"passcode": "nope-nope"})[0], 401)
        st, dev = anon.call("POST", "/api/v1/pair", {"passcode": "lan-secret-9", "name": "pc", "scopes": "ro"})
        self.assertEqual(st, 200)
        anon.token = dev["token"]
        self.assertEqual(anon.call("GET", "/api/v1/collections")[0], 200)
        self.assertEqual(anon.call("POST", "/api/v1/search", {"q": "電池"})[0], 200)
        self.assertEqual(anon.call("POST", "/api/v1/collections", {"name": "y"})[0], 403)  # read-only device
        self.assertEqual(anon.call("GET", "/api/settings")[0], 403)  # admin only
        # not from LAN -> token refused
        with mock.patch("qnaplibrary.auth.is_local_network", return_value=False):
            self.assertEqual(anon.call("GET", "/api/v1/collections")[0], 401)

    def test_06_mcp(self):
        st, dev = self.c.call("POST", "/api/devices", {"name": "agent"})
        m = Client(self.srv.base)
        m.token = dev["token"]
        st, r = m.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "QnapLibrary")
        st, r = m.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertIn("search", [t["name"] for t in r["result"]["tools"]])
        st, r = m.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "add_documents", "arguments": {"collection": "mcp-notes", "documents": [{"id": "n1", "title": "メモ", "body": "量子コンピュータの動向"}]}}})
        self.assertFalse(r["result"]["isError"])
        st, r = m.call("POST", "/mcp", {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search", "arguments": {"query": "量子"}}})
        self.assertIn("n1", r["result"]["content"][0]["text"])
        st, _ = m.call("POST", "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, raw=True)
        self.assertEqual(st, 202)

    def test_07_patent_flow(self):
        st, p = self.c.call("POST", "/api/v1/patents", {"title": "電池の電解質", "data": {"problem": "発火"}})
        pid = p["id"]
        self.c.call("POST", "/api/v1/patents/%d/claims" % pid, {"text": "【請求項１】正極と、負極と、硫化物系固体電解質層と、を備える電池。"})
        st, p = self.c.call("POST", "/api/v1/patents/%d/events" % pid, {"kind": "filing", "date": "2026-01-15"})
        self.assertTrue(any(d["key"] == "exam_request" for d in p["deadlines"]))
        st, chart = self.c.call("POST", "/api/v1/patents/%d/chart" % pid, {"claim_no": 1})
        self.assertEqual([r["element"]["label"] for r in chart["rows"]], ["A", "B", "C"])
        st, p = self.c.call("PATCH", "/api/v1/patents/%d" % pid, {"stage": "prior_art"})
        self.assertEqual(p["stage"], "prior_art")
        self.assertEqual(self.c.call("PATCH", "/api/v1/patents/%d" % pid, {"stage": "bogus"})[0], 400)
        st, r = self.c.call("POST", "/api/v1/patents/%d/assist" % pid, {"task": "novelty", "provider": "qnapassistant"})
        self.assertEqual(st, 502)  # no LLM running in tests: clean error, not 500
        with mock.patch.object(self.srv.app.providers, "chat", return_value={"content": "結果", "model": "m"}):
            st, r = self.c.call("POST", "/api/v1/patents/%d/assist" % pid, {"task": "novelty"})
            self.assertEqual(r["answer"], "結果")

    def test_08_secrets_never_returned(self):
        self.c.call("PUT", "/api/secrets/openrouter_api_key", {"value": "sk-or-v1-supersecret"})
        st, s = self.c.call("GET", "/api/settings")
        self.assertNotIn("supersecret", json.dumps(s))
        st, b = self.c.call("GET", "/api/debug/bundle")
        self.assertNotIn("supersecret", json.dumps(b))
        st, p = self.c.call("GET", "/api/llm/providers")
        self.assertNotIn("supersecret", json.dumps(p))
        self.assertTrue(b["secrets"]["openrouter_api_key"]["configured"])

    def test_09_openrouter_body(self):
        prov = self.srv.app.providers
        p = {"id": "or", "type": "openrouter", "base_url": "https://openrouter.ai/api/v1", "model": "a/b",
             "options": {"fallback_models": ["c/d"], "provider": {"sort": "price", "data_collection": "deny", "order": []},
                         "reasoning": {"effort": "high"}, "temperature": 0.2, "web_search": True}}
        body = prov.build_body(p, [{"role": "user", "content": "x"}])
        self.assertEqual(body["models"], ["a/b", "c/d"])
        self.assertEqual(body["provider"], {"sort": "price", "data_collection": "deny"})
        self.assertEqual(body["reasoning"], {"effort": "high"})
        self.assertEqual(body["plugins"][0]["id"], "web")
        self.assertEqual(body["temperature"], 0.2)

    def test_10_debug_and_schema(self):
        st, b = self.c.call("GET", "/api/debug/bundle")
        for k in ("errors", "requests", "searches", "store", "version"):
            self.assertIn(k, b)
        st, s = self.c.call("GET", "/api/v1/schema")
        self.assertTrue(any(r["path"] == "/api/v1/search" for r in s["routes"]))

    def test_11_ssrf_guard(self):
        from qnaplibrary import connectors
        with self.assertRaises(connectors.ConnectorError):
            connectors.rss("http://127.0.0.1:1/feed")


if __name__ == "__main__":
    unittest.main()
