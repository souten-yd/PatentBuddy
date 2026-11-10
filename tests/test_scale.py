"""Large-ingestion regression checks without a network or AI dependency."""
import os
import concurrent.futures
import selectors
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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
        self.assertEqual(self.store.fts_search("正極"), [])

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
        exact = self.store.list_documents(self.cid, ext_id="3")
        self.assertEqual([d["ext_id"] for d in exact["items"]], ["3"])
        self.assertIsNone(exact["total"])
        self.assertEqual(self.store.list_documents(self.cid, ext_id="missing")["items"], [])
        indexes = {r["name"] for r in self.store.q(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='documents'")}
        self.assertIn("documents_coll_id", indexes)
        plan = self.store.q("EXPLAIN QUERY PLAN SELECT id FROM documents "
                            "WHERE collection_id=? AND id<? ORDER BY id DESC LIMIT 10", (self.cid, 9999))
        self.assertTrue(any("documents_coll_id" in row[3] for row in plan), [tuple(r) for r in plan])

    def test_failed_begin_releases_python_lock(self):
        other = sqlite3.connect(self.store.path, isolation_level=None)
        self.store.db.execute("PRAGMA busy_timeout=20")
        try:
            other.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                with self.store.tx():
                    self.fail("writer should not enter")
            def try_lock():
                acquired = self.store.lock.acquire(timeout=.2)
                if acquired:
                    self.store.lock.release()
                return acquired
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                self.assertTrue(pool.submit(try_lock).result(timeout=2))
        finally:
            other.execute("ROLLBACK")
            other.close()
            self.store.db.execute("PRAGMA busy_timeout=30000")
        self.assertEqual(self.store.add_documents(self.cid, [{"id":"after-lock", "body":"再開"}])["added"], 1)

    def test_disk_full_rolls_back_and_next_request_can_resume(self):
        self.store.add_documents(self.cid, [{"id": "stable", "body": "確定本文"}])
        pages = self.store.one("PRAGMA page_count")[0]
        self.store.db.execute("PRAGMA max_page_count=%d" % (pages + 1))
        with self.assertRaisesRegex(sqlite3.OperationalError, "database or disk is full"):
            self.store.add_documents(self.cid, [
                {"id": "stable", "body": "未確定の更新"},
                {"id": "oversize-for-test", "body": "電池" * 100000}])
        self.assertFalse(self.store.db.in_transaction)
        self.assertEqual(self.store.one("SELECT COUNT(*) FROM documents")[0], 1)
        self.assertEqual(self.store.one("SELECT body FROM documents")[0], "確定本文")
        self.assertEqual(self.store.fts_search("未確定"), [])
        self.store.db.execute("PRAGMA max_page_count=1000000")
        self.assertEqual(self.store.add_documents(self.cid, [{"id": "resume", "body": "再開本文"}])["added"], 1)
        self.assertEqual(self.store.one("PRAGMA quick_check")[0], "ok")

    def test_batch_lookup_respects_parameter_limit_and_collection_key(self):
        if hasattr(self.store.db, "setlimit"):
            self.store.db.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 500)
        docs = [{"id": "shared-%d" % i, "body": "電池"} for i in range(850)]
        self.assertEqual(self.store.add_documents(self.cid, docs)["added"], 850)
        before = self.store.db.total_changes
        self.assertEqual(self.store.add_documents(self.cid, docs)["unchanged"], 850)
        self.assertEqual(self.store.db.total_changes, before)
        other = self.store.create_collection("other")["id"]
        self.assertEqual(self.store.add_documents(other, docs[:1])["added"], 1)
        self.assertEqual(self.store.list_documents(other, ext_id="shared-0")["items"][0]["collection_id"], other)

    def test_fts_unavailable_still_supports_ingestion_and_search(self):
        with mock.patch.object(Store, "_init_fts", return_value=False):
            fallback = Store(os.path.join(self.tmp.name, "no-fts.sqlite3"))
        try:
            cid = fallback.create_collection("fallback")["id"]
            docs = [{"id": "IEC-SYN", "body": "電池の構造", "meta": {"revision": "2026"}}]
            self.assertEqual(fallback.add_documents(cid, docs)["added"], 1)
            before = fallback.db.total_changes
            self.assertEqual(fallback.add_documents(cid, docs)["unchanged"], 1)
            self.assertTrue(fallback.fts_search("電池", [cid]))
            self.assertEqual(fallback.list_documents(cid, cursor="start")["items"][0]["ext_id"], "IEC-SYN")
            self.assertEqual(fallback.db.total_changes, before)
        finally:
            fallback.close()

    def test_source_and_explicit_sections_are_not_silently_skipped(self):
        doc = {"id": "provenance", "body": "原本本文", "source": "first",
               "sections": {"要約": "旧索引"}}
        self.store.add_documents(self.cid, [doc])
        changed_source = dict(doc, source="corrected")
        self.assertEqual(self.store.add_documents(self.cid, [changed_source])["updated"], 1)
        self.assertEqual(self.store.one("SELECT source FROM documents WHERE ext_id='provenance'")[0], "corrected")
        changed_sections = dict(changed_source, sections={"要約": "新索引"})
        self.assertEqual(self.store.add_documents(self.cid, [changed_sections])["updated"], 1)
        self.assertEqual(self.store.fts_search("旧索引"), [])
        self.assertEqual(len(self.store.fts_search("新索引")), 1)
        before = self.store.db.total_changes
        self.assertEqual(self.store.add_documents(self.cid, [changed_sections])["unchanged"], 1)
        self.assertEqual(self.store.db.total_changes, before)

    def test_concurrent_batches_keep_body_chunks_and_index_consistent(self):
        def write(i):
            return self.store.add_documents(self.cid, [
                {"id": "shared", "body": "電池 alpha%d" % i},
                {"id": "shared", "body": "電池 omega%d" % i}])
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(write, range(12)))
        self.assertEqual(sum(r["added"] for r in results), 1)
        row = self.store.one("SELECT id,body FROM documents WHERE ext_id='shared'")
        chunks = self.store.q("SELECT text FROM chunks WHERE doc_id=?", (row["id"],))
        self.assertEqual([r["text"] for r in chunks], [row["body"]])
        self.assertEqual(len(self.store.fts_search(row["body"].split()[-1])), 1)
        self.assertEqual(self.store.one("PRAGMA quick_check")[0], "ok")

    def test_batch_failure_is_atomic_and_cursor_survives_delete(self):
        first = self.store.add_documents(self.cid, [{"id": str(i), "body": "本文"} for i in range(6)])
        page = self.store.list_documents(self.cid, cursor="start", limit=2)
        # The second record fails JSON serialization after the first update.
        with self.assertRaises(TypeError):
            self.store.add_documents(self.cid, [
                {"id": "0", "body": "変更してはいけない"},
                {"id": "bad", "body": "無効", "meta": {"bad": object()}}])
        self.assertEqual(self.store.get_document(first["ids"][0])["body"], "本文")
        self.assertEqual(self.store.fts_search("変更してはいけない"), [])
        with self.store.tx() as db:
            db.execute("DELETE FROM documents WHERE id=?", (page["next_cursor"],))
        remaining = self.store.list_documents(self.cid, cursor=page["next_cursor"], limit=10)
        self.assertEqual(len(remaining["items"]), 4)
        self.assertFalse(remaining["has_more"])

    def test_crash_before_commit_preserves_previous_batch(self):
        path = os.path.join(self.tmp.name, "crash.sqlite3")
        initial = Store(path)
        cid = initial.create_collection("crash")["id"]
        initial.add_documents(cid, [{"id": "stable", "body": "確定した電池"}])
        initial.close()
        code = """
import sys, threading
from qnaplibrary.store import Store
s = Store(sys.argv[1])
def trace(sql):
    if sql == 'COMMIT':
        print('before-commit', flush=True)
        threading.Event().wait(30)
s.db.set_trace_callback(trace)
s.add_documents(int(sys.argv[2]), [{'id':'stable','body':'未確定'}, {'id':'partial','body':'未確定'}])
"""
        child = subprocess.Popen([sys.executable, "-c", code, path, str(cid)], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(10), "child did not reach commit")
                self.assertEqual(child.stdout.readline().strip(), "before-commit")
            child.kill()
            child.wait(timeout=10)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
        recovered = Store(path)
        try:
            self.assertEqual(recovered.one("PRAGMA quick_check")[0], "ok")
            self.assertEqual(recovered.one("SELECT COUNT(*) FROM documents")[0], 1)
            self.assertEqual(recovered.one("SELECT body FROM documents")[0], "確定した電池")
            self.assertEqual(len(recovered.fts_search("電池")), 1)
            self.assertEqual(recovered.fts_search("未確定"), [])
            self.assertEqual(recovered.add_documents(cid, [{"id":"stable", "body":"確定した電池"}])["unchanged"], 1)
        finally:
            recovered.close()


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
            st, exact = client.call("GET", "/api/v1/collections/big-patents/documents?ext_id=3")
            self.assertEqual(st, 200, exact)
            self.assertEqual([d["ext_id"] for d in exact["items"]], ["3"])
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
