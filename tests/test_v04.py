import json
import time
import unittest
from unittest import mock

from qnaplibrary import connectors
from tests.helpers import Client, LiveServer


class V04Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = LiveServer()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def setUp(self):
        self.c = Client(self.srv.base)
        if self.srv.app.auth.admin_configured():
            self.c.csrf = self.c.call("POST", "/api/auth/login", {"password": "correct-horse-1"})[1]["csrf"]
        else:
            self.c.login_setup()

    def test_research_job(self):
        self.c.call("POST", "/api/v1/collections", {"name": "res", "kind": "patent"})
        self.c.call("POST", "/api/v1/collections/res/documents", {"documents": [
            {"id": "P1", "title": "硫化物系固体電解質", "body": "硫化物系固体電解質はイオン伝導度が高いが水分に弱い。"}]})
        answers = iter([{"content": '{"sub_questions": ["硫化物系固体電解質の課題"], "news_query_en": ""}'},
                        {"content": "## 要約\n水分に弱い [1]", "model": "m"}])
        with mock.patch.object(self.srv.app.providers, "chat", side_effect=lambda *a, **k: next(answers)):
            st, j = self.c.call("POST", "/api/v1/research", {"question": "固体電解質の課題は？"})
            self.assertEqual(st, 200)
            for _ in range(100):
                st, j = self.c.call("GET", "/api/v1/research/%d" % j["id"])
                if j["status"] != "running":
                    break
                time.sleep(0.05)
        self.assertEqual(j["status"], "done", j)
        self.assertEqual(j["result"]["sources"][0]["ext_id"], "P1")
        doc = self.srv.app.store.get_document(j["result"]["doc_id"])
        self.assertIn("水分に弱い", doc["body"])
        st, lst = self.c.call("GET", "/api/v1/research")
        self.assertTrue(lst["jobs"])

    def test_standard_numbers_normalized(self):
        self.c.call("POST", "/api/v1/collections", {"name": "std", "kind": "standard"})
        st, r = self.c.call("POST", "/api/v1/collections/std/import", {"format": "csv", "data":
                            "id,title,date,status,org,ics,intl\nJIS B 1194,六角穴付き皿ボルト,2006-01-20,有効,JIS,21.060.10,ISO 10642\n"})
        self.assertEqual(r["added"], 1)
        for q in ("JISB1194", "JIS B1194", "ＪＩＳ　Ｂ　１１９４"):
            st, r = self.c.call("POST", "/api/v1/search", {"q": q, "collections": ["std"]})
            self.assertEqual(r["results"][0]["ext_id"], "JIS B 1194", q)
        st, raw = self.c.call("GET", "/api/v1/templates/standards.csv", raw=True)
        self.assertIn("id,title".encode(), raw)

    def test_market_connectors_parse(self):
        estat = {"GET_STATS_LIST": {"RESULT": {"STATUS": 0}, "DATALIST_INF": {"TABLE_INF": [
            {"@id": "0003", "STAT_NAME": {"$": "工業統計"}, "TITLE": {"$": "半導体生産"}, "OPEN_DATE": "2026-01-15",
             "GOV_ORG": {"$": "経済産業省"}, "SURVEY_DATE": "202512"}]}}}
        with mock.patch.object(connectors, "http_get", return_value=json.dumps(estat).encode()):
            d = connectors.estat("半導体", "app")
        self.assertEqual(d[0]["id"], "estat:0003")
        self.assertEqual(d[0]["date"], "2026-01-15")
        ed = {"metadata": {"status": "200"}, "results": [{"docID": "S100", "filerName": "トヨタ自動車株式会社",
                                                          "docDescription": "有価証券報告書", "submitDateTime": "2026-06-20 09:00"},
                                                         {"docID": "S101", "filerName": "別会社", "docDescription": "臨時報告書"}]}
        with mock.patch.object(connectors, "http_get", return_value=json.dumps(ed).encode()):
            d = connectors.edinet("2026-06-20", "k", "トヨタ")
        self.assertEqual([x["id"] for x in d], ["edinet:S100"])
        sec = {"name": "Apple Inc.", "tickers": ["AAPL"], "filings": {"recent": {
            "form": ["10-K", "4"], "accessionNumber": ["0000320193-25-000079", "x"], "filingDate": ["2025-10-31", "2025-11-01"],
            "primaryDocument": ["aapl-20250927.htm", "y"], "primaryDocDescription": ["10-K", ""]}}}
        with mock.patch.object(connectors, "http_get", return_value=json.dumps(sec).encode()):
            d = connectors.sec_filings("320193", "Taro taro@example.com")
        self.assertEqual(len(d), 1)
        self.assertIn("/320193/000032019325000079/aapl-20250927.htm", d[0]["url"])
        with self.assertRaises(connectors.ConnectorError):
            connectors.sec_filings("320193", "no-contact")


if __name__ == "__main__":
    unittest.main()
