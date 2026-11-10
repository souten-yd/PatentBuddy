"""Large-ingestion regression checks without a network or AI dependency."""
import os
import tempfile
import unittest

from qnaplibrary.store import Store, StoreError
from tests.helpers import Client, LiveServer


class ScaleStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "scale.sqlite3"))
        self.collection = self.store.create_collection("patents", kind="patent")
        self.cid = self.collection["id"]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_batch_dedup_last_write_and_noop_has_zero_changes(self):
        docs = [{"id": "JP0001", "title": "文献1", "body": "固体電解質層"},
                {"id": "JP0002", "title": "文献2", "body": "電池"}]
        first = self.store.add_documents(self.cid, docs)
        self.assertEqual(first["added"], 2)
        before_total_changes = self.store.db.total_changes
        before_updated = self.store.get_collection(self.cid)["updated"]
        repeated = self.store.add_documents(self.cid, docs)
        self.assertEqual(repeated["unchanged"], 2)
        self.assertEqual(self.store.db.total_changes, before_total_changes)
        self.assertEqual(self.store.get_collection(self.cid)["updated"], before_updated)
        batch = self.store.add_documents(self.cid, [
            dict(docs[0]),
            {"id": "JP0002", "title": "文献2", "body": "正極"},
            {"id": "JP0002", "title": "文献2", "body": "負極"},
            {"id": "JP0003", "title": "文献3", "body": "有機半導体"},
            {"id": "JP0003", "title": "文献3", "body": "有機半導体"}])
        self.assertEqual((batch["added"], batch["updated"], batch["unchanged"]), (1, 2, 2))
        self.assertEqual(len(self.store.list_documents(self.cid)["items"]), 3)
        current = self.store.one("SELECT body FROM documents WHERE ext_id='JP0002'")
        self.assertEqual(current["body"], "負極")
        self.assertEqual(self.store.search_chunks("不存在") if hasattr(self.store, "search_chunks") else
                         self.store.fts_search("正極"), [])

    def test_cursor_pages_are_disjoint_across_new_insert(self):
        docs = [{"id": "JP%04d" % i, "title": "公開公報 %d" % i,
                 "body": "固体電解質が記載された本文 " * 30} for i in range(1, 8)]
        self.assertEqual(self.store.add_documents(self.cid, docs)["added"], len(docs))
        p1 = self.store.list_documents(self.cid, limit=3, cursor="start")
        self.assertIsNone(p1["total"])
        self.assertEqual(len(p1["items"]), 3)
        self.assertTrue(p1["has_more"])
        self.assertTrue(all("body" not in item and item["body_chars"] > 0 for item in p1["items"]))
        self.store.add_documents(self.cid, [{"id": "JP9999", "title": "追加された文献", "body": "追加"}])
        p2 = self.store.list_documents(self.cid, limit=3, cursor=p1["next_cursor"])
        p3 = self.store.list_documents(self.cid, limit=3, cursor=p2["next_cursor"])
        seen = [r["id"] for page in (p1, p2, p3) for r in page["items"]]
        self.assertEqual(len(seen), 7)
        self.assertEqual(len(set(seen)), 7)
        self.assertEqual(seen, sorted(seen, reverse=True))
        self.assertFalse(p3["has_more"])
        self.assertIsNone(p3["next_cursor"])
        self.assertEqual(self.store.list_documents(self.cid, limit=2)["total"], 8)
        for invalid in ("junk", "-1", "9223372036854775808"):
            with self.assertRaises(StoreError):
                self.store.list_documents(self.cid, cursor=invalid)

    def test_cursor_filters_and_index_present(self):
        docs = [{"id": str(i), "title": "対象文献" if i % 2 else "ノイズ", "body": "内容"}
                for i in range(1, 8)]
        self.store.add_documents(self.cid, docs)
        a = self.store.list_documents(self.cid, cursor="start", q="対象", limit=2)
        b = self.store.list_documents(self.cid, cursor=a["next_cursor"], q="対象", limit=2)
        self.assertEqual(len(a["items"]) + len(b["items"]), 4)
        self.assertEqual(self.store.list_documents(self.cid, offset=2, limit=3)["total"], 7)
        indexes = {r["name"] for r in self.store.q(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='documents'")}
        self.assertIn("documents_coll_id", indexes)
        plan = self.store.q("EXPLAIN QUERY PLAN SELECT id FROM documents "
                            "WHERE collection_id=? AND id<? ORDER BY id DESC LIMIT 10", (self.cid, 9999))
        self.assertTrue(plan)


class ScaleApiTest(unittest.TestCase):
    def test_cursor_endpoint_is_authenticated_and_bounded(self):
        srv = LiveServer()
        try:
            client = Client(srv.base)
            client.login_setup()
            client.call("POST", "/api/v1/collections", {"name": "big-patents", "kind": "patent"})
            st, result = client.call("POST", "/api/v1/collections/big-patents/documents", {
                "documents": [{"id": str(i), "title": "特許%s" % i, "body": "特許請求の範囲"} for i in range(5)]})
            self.assertEqual(st, 200, result)
            anon = Client(srv.base)
            self.assertEqual(anon.call("GET", "/api/v1/collections/big-patents/documents?cursor=start")[0], 401)
            st, page = client.call("GET", "/api/v1/collections/big-patents/documents?cursor=start&limit=2")
            self.assertEqual(st, 200, page)
            self.assertEqual(len(page["items"]), 2)
            self.assertTrue(page["has_more"])
            st, second = client.call("GET", "/api/v1/collections/big-patents/documents?cursor=%s&limit=2" %
                                     page["next_cursor"])
            self.assertEqual(st, 200, second)
            self.assertFalse(set(d["id"] for d in page["items"]) &
                             set(d["id"] for d in second["items"]))
            self.assertEqual(client.call("GET", "/api/v1/collections/big-patents/documents?cursor=bad")[0], 400)
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
