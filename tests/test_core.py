import datetime as dt
import os
import tempfile
import unittest

from qnaplibrary import patents, textproc
from qnaplibrary.config import Config
from qnaplibrary.search import Searcher, rrf
from qnaplibrary.store import Store, StoreError


class TextprocTest(unittest.TestCase):
    def test_bigrams_and_words(self):
        self.assertEqual(textproc.tokens("半導体"), ["半導", "導体"])
        self.assertIn("lithium", textproc.tokens("Lithium battery"))
        self.assertIn("h01l_21", textproc.tokens("H01L-21"))

    def test_nfkc(self):
        self.assertEqual(textproc.tokens("ＡＢＣ１２３"), ["abc123"])

    def test_parse_query(self):
        self.assertEqual(textproc.parse_query("固体電解質"), '"固体 体電 電解 解質"')
        expr = textproc.parse_query("電池 OR キャパシタ -液体")
        self.assertIn(" OR ", expr)
        self.assertIn(" NOT ", expr)
        self.assertIsNone(textproc.parse_query("  -x "))

    def test_split_claims(self):
        claims = textproc.split_claims("【請求項１】Ａを備える装置。【請求項２】Ｂを更に備える請求項１に記載の装置。")
        self.assertEqual([n for n, _ in claims], [1, 2])
        self.assertEqual(textproc.split_claims("1. A device.\n2. The device of claim 1.")[1][0], 2)

    def test_chunking(self):
        text = "。".join("文%d" % i * 30 for i in range(80))
        chunks = textproc.chunk_text(text, size=500, overlap=50)
        self.assertGreater(len(chunks), 3)
        self.assertTrue(all(len(c) <= 700 for c in chunks))


class StoreSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.sqlite3"))
        self.config = Config(self.tmp.name)
        self.search = Searcher(self.store, self.config)
        c = self.store.create_collection("jp", "patent")
        self.cid = c["id"]
        self.store.add_documents(self.cid, [
            {"id": "A", "title": "固体電解質電池", "sections": {"claims": "【請求項１】硫化物系固体電解質層を備える電池。【請求項２】厚さ10μm以下の請求項１の電池。"}},
            {"id": "B", "title": "半導体装置", "body": "シリコン基板とゲート絶縁膜を有する半導体装置。"},
        ])

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_claims_indexed_one_per_chunk(self):
        doc = self.store.get_document(1, with_chunks=True)
        self.assertEqual([c["section"] for c in doc["chunks"]], ["claim 1", "claim 2"])

    def test_keyword_search_japanese(self):
        r = self.search.search("固体電解質", limit=5)["results"]
        self.assertEqual(r[0]["ext_id"], "A")
        self.assertEqual(self.search.search("ゲート絶縁", limit=5)["results"][0]["ext_id"], "B")
        self.assertEqual(self.search.search("存在しない語句", limit=5)["results"], [])

    def test_upsert_unchanged_and_update(self):
        r = self.store.add_documents(self.cid, [{"id": "B", "title": "半導体装置", "body": "シリコン基板とゲート絶縁膜を有する半導体装置。"}])
        self.assertEqual(r["unchanged"], 1)
        r = self.store.add_documents(self.cid, [{"id": "B", "title": "半導体装置", "body": "新しい本文 トランジスタ"}])
        self.assertEqual(r["updated"], 1)
        self.assertEqual(self.search.search("ゲート絶縁")["results"], [])
        self.assertEqual(self.search.search("トランジスタ")["results"][0]["ext_id"], "B")

    def test_vectors_hybrid(self):
        chunks = [r["id"] for r in self.store.q("SELECT id FROM chunks ORDER BY id")]
        vecs = [[1, 0, 0], [0.9, 0.1, 0], [0, 1, 0]]
        self.store.put_vectors(list(zip(chunks, vecs)), "test")
        res = self.search.search("電池", qvec=[1, 0, 0])
        self.assertTrue(any(s["stage"] == "vector" for s in res["trace"]["stages"]))
        self.assertEqual(res["results"][0]["ext_id"], "A")
        self.assertEqual(self.search.search("zzz", mode="vector", qvec=[0, 1, 0])["results"][0]["ext_id"], "B")

    def test_delete_collection(self):
        self.store.delete_collection(self.cid)
        self.assertEqual(self.store.stats()["chunks"], 0)
        with self.assertRaises(StoreError):
            self.store.get_collection(self.cid)

    def test_rrf(self):
        fused = rrf([[(1, 5), (2, 4)], [(2, 0.9), (3, 0.5)]])
        self.assertEqual(fused[0][0], 2)


class PatentsTest(unittest.TestCase):
    def test_claim_elements(self):
        els = patents.claim_elements("正極と、負極と、固体電解質層と、を備える電池。")
        self.assertEqual([e["label"] for e in els], ["A", "B", "C", "結び"])

    def test_deadlines(self):
        today = dt.date(2026, 1, 1)
        d = {x["key"]: x for x in patents.deadlines([{"kind": "filing", "date": "2025-04-01"}], today=today)}
        self.assertEqual(d["exam_request"]["due"], "2028-04-01")
        self.assertEqual(d["publication"]["due"], "2026-10-01")
        d = {x["key"]: x for x in patents.deadlines([{"kind": "oa_dispatch", "date": "2026-01-10"}], today=today)}
        self.assertEqual(d["oa_response"]["due"], "2026-03-11")
        d = {x["key"]: x for x in patents.deadlines([{"kind": "oa_dispatch", "date": "2026-01-10"}], foreign_resident=True, today=today)}
        self.assertEqual(d["oa_response"]["due"], "2026-04-10")
        d = {x["key"]: x for x in patents.deadlines([{"kind": "allowance_served", "date": "2026-01-10"}], today=today)}
        self.assertEqual(d["fee"]["due"], "2026-02-09")
        d = {x["key"]: x for x in patents.deadlines([{"kind": "filing", "date": "2020-02-29"},
                                                      {"kind": "registration", "date": "2024-06-01"}], today=today)}
        self.assertEqual(d["annuity"]["due"], "2025-02-28")

    def test_month_end(self):
        self.assertEqual(patents._add_months(dt.date(2024, 1, 31), 1), dt.date(2024, 2, 29))


if __name__ == "__main__":
    unittest.main()
