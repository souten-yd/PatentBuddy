import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from tests.helpers import Client, LiveServer

RECEIVED = []


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        RECEIVED.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


class WatchNotifyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = LiveServer()
        cls.hook = HTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=cls.hook.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.hook.shutdown()
        cls.srv.close()

    def setUp(self):
        self.c = Client(self.srv.base)
        if self.srv.app.auth.admin_configured():
            st, body = self.c.call("POST", "/api/auth/login", {"password": "correct-horse-1"})
            self.c.csrf = body["csrf"]
        else:
            self.c.login_setup()
        RECEIVED.clear()
        self.c.call("PUT", "/api/settings", {"notify": {"webhooks": [
            {"kind": "json", "url": "http://127.0.0.1:%d/hook" % self.hook.server_address[1], "label": "t"}]}})

    def test_watch_scores_new_docs_and_promotes_hit(self):
        st, p = self.c.call("POST", "/api/v1/patents", {"title": "全固体電池"})
        self.c.call("POST", "/api/v1/patents/%d/claims" % p["id"], {"text": "【請求項１】硫化物系固体電解質層を備える全固体電池。"})
        st, w = self.c.call("POST", "/api/v1/watches", {"name": "EPO電池", "connector": "epo_ops", "params": {"query": "x"},
                                                         "collection": "watch-epo", "patent_id": p["id"], "interval_hours": 1})
        self.assertEqual(w["interval_hours"], 6)  # minimum enforced
        docs = [{"id": "EP1", "title": "硫化物系固体電解質を用いた電池", "body": "固体電解質層"},
                {"id": "EP2", "title": "自動車のドア", "body": "ヒンジ機構"}]
        with mock.patch("qnaplibrary.connectors.run", return_value=docs):
            st, r = self.c.call("POST", "/api/v1/watches/%d/run" % w["id"], {})
        self.assertIn("新規 2", r["last_status"])
        st, hits = self.c.call("GET", "/api/v1/watch-hits?patent_id=%d" % p["id"])
        self.assertEqual(hits["hits"][0]["ext_id"], "EP1")
        self.assertTrue(RECEIVED and "新しい候補" in RECEIVED[0]["title"])
        with mock.patch("qnaplibrary.connectors.run", return_value=docs):  # same docs again: no new hits
            st, r = self.c.call("POST", "/api/v1/watches/%d/run" % w["id"], {})
        self.assertIn("新規 0", r["last_status"])
        self.c.call("POST", "/api/v1/watch-hits/%d" % hits["hits"][0]["id"], {"status": "relevant", "category": "X"})
        st, p2 = self.c.call("GET", "/api/v1/patents/%d" % p["id"])
        self.assertEqual(p2["refs"][0]["category"], "X")
        self.assertEqual(self.srv.app.watches.due(), [])

    def test_deadline_reminder_sent_once(self):
        import datetime as dt
        st, p = self.c.call("POST", "/api/v1/patents", {"title": "期限テスト"})
        oa = (dt.date.today() - dt.timedelta(days=55)).isoformat()  # response due in 5 days
        self.c.call("POST", "/api/v1/patents/%d/events" % p["id"], {"kind": "oa_dispatch", "date": oa})
        st, r = self.c.call("POST", "/api/notify/deadlines", {})
        self.assertGreaterEqual(r["sent"], 1)
        self.assertTrue(any("期限テスト" in m["title"] for m in RECEIVED))
        n = len(RECEIVED)
        self.c.call("POST", "/api/notify/deadlines", {})
        self.assertEqual(len(RECEIVED), n)  # not repeated

    def test_classification_and_law_in_assist(self):
        self.c.call("POST", "/api/v1/collections", {"name": "ipc", "kind": "classification"})
        st, r = self.c.call("POST", "/api/v1/collections/ipc/import", {"format": "codes", "data":
                            "H01M10/0562\t固体電解質を有するもの\nH01L21/02  半導体装置の製造\n"})
        self.assertEqual(r["added"], 2)
        st, r = self.c.call("GET", "/api/v1/classify?q=" + __import__("urllib.parse").parse.quote("固体電解質"))
        self.assertEqual(r["codes"][0]["code"], "H01M10/0562")
        self.c.call("POST", "/api/v1/collections", {"name": "審査基準", "kind": "law"})
        self.c.call("POST", "/api/v1/collections/%s/documents" % __import__("urllib.parse").parse.quote("審査基準"), {"documents": [
            {"id": "III-2-2", "title": "進歩性", "body": "進歩性の判断では、主引用発明から出発して論理付けができるかを検討する。固体電解質の例。"}]})
        st, p = self.c.call("POST", "/api/v1/patents", {"title": "固体電解質の電池", "data": {"solution": "固体電解質"}})
        captured = {}

        def fake_chat(messages, provider=None, **kw):
            captured["m"] = messages
            return {"content": "ok", "model": "m"}
        with mock.patch.object(self.srv.app.providers, "chat", side_effect=fake_chat):
            self.c.call("POST", "/api/v1/patents/%d/assist" % p["id"], {"task": "inventive_step"})
            self.assertIn("[基準1] 進歩性", captured["m"][1]["content"])
            self.c.call("POST", "/api/v1/patents/%d/assist" % p["id"], {"task": "search_plan"})
            self.assertIn("H01M10/0562", captured["m"][1]["content"])


if __name__ == "__main__":
    unittest.main()
