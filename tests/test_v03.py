import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from tests.helpers import Client, LiveServer

ROOT = Path(__file__).resolve().parents[1]
POINTS = {}
COLL = {}


class Fake(BaseHTTPRequestHandler):
    """Minimal fake of Qdrant REST + an OpenAI-compatible /embeddings endpoint."""

    def _send(self, obj, code=200):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n)) if n else {}

    def do_GET(self):
        name = self.path.split("/")[2]
        if name not in COLL:
            return self._send({"status": "not found"}, 404)
        self._send({"result": {"points_count": len(POINTS), "status": "green", "config": {"params": {"vectors": {"size": COLL[name]}}}}})

    def do_DELETE(self):
        COLL.clear()
        POINTS.clear()
        self._send({"result": True})

    def do_PUT(self):
        b = self._body()
        parts = self.path.split("?")[0].split("/")
        if len(parts) == 3:
            COLL[parts[2]] = b["vectors"]["size"]
        elif parts[3] == "points":
            for p in b["points"]:
                POINTS[p["id"]] = p
        self._send({"result": True})

    def do_POST(self):
        b = self._body()
        if self.path.endswith("/embeddings"):
            vecs = [[1.0 if "電池" in t else 0.0, 1.0 if "ドア" in t else 0.0, 0.5] for t in b["input"]]
            return self._send({"data": [{"index": i, "embedding": v} for i, v in enumerate(vecs)]})
        q = b["vector"]
        allowed = None
        for m in (b.get("filter") or {}).get("must", []):
            if m["key"] == "collection_id":
                allowed = set(m["match"]["any"])

        def cos(a, c):
            return sum(x * y for x, y in zip(a, c)) / ((math.sqrt(sum(x * x for x in a)) or 1) * (math.sqrt(sum(x * x for x in c)) or 1))
        res = sorted(({"id": pid, "score": cos(q, p["vector"])} for pid, p in POINTS.items()
                      if allowed is None or p["payload"]["collection_id"] in allowed), key=lambda r: -r["score"])
        self._send({"result": res[:b["limit"]]})

    def log_message(self, *a):
        pass


class V03Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = LiveServer()
        cls.fake = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.fake.serve_forever, daemon=True).start()
        cls.fake_url = "http://127.0.0.1:%d" % cls.fake.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.fake.shutdown()
        cls.srv.close()

    def setUp(self):
        self.c = Client(self.srv.base)
        if self.srv.app.auth.admin_configured():
            self.c.csrf = self.c.call("POST", "/api/auth/login", {"password": "correct-horse-1"})[1]["csrf"]
        else:
            self.c.login_setup()

    def test_qdrant_mirror_and_search(self):
        app = self.srv.app
        self.c.call("PUT", "/api/settings", {"vector_backend": {"type": "qdrant", "url": self.fake_url, "collection": "t"}})
        self.c.call("POST", "/api/v1/collections", {"name": "qd", "kind": "generic"})
        self.c.call("POST", "/api/v1/collections/qd/documents", {"documents": [
            {"id": "a", "title": "電池", "body": "電池の話"}, {"id": "b", "title": "ドア", "body": "ドアの話"}]})
        chunks = [r["id"] for r in app.store.q("SELECT id FROM chunks WHERE collection_id=(SELECT id FROM collections WHERE name='qd') ORDER BY id")]
        app.store.put_vectors([(chunks[0], [1, 0, 0]), (chunks[1], [0, 1, 0])], "m")
        self.assertEqual(len(POINTS), 2)
        res = app.searcher.search("zzz", ["qd"], mode="vector", qvec=[0, 1, 0])
        self.assertEqual(res["results"][0]["ext_id"], "b")
        self.assertTrue(any(s["stage"] == "qdrant" for s in res["trace"]["stages"]))
        POINTS.clear()
        app.sync_qdrant(recreate=True)
        for _ in range(50):
            if not app.qdrant_sync["running"]:
                break
            __import__("time").sleep(0.05)
        self.assertGreaterEqual(len(POINTS), 2)
        self.c.call("PUT", "/api/settings", {"vector_backend": {"type": "memory"}})

    def test_rerank_and_date_filter(self):
        app = self.srv.app
        self.c.call("POST", "/api/v1/collections", {"name": "rr", "kind": "news"})
        self.c.call("POST", "/api/v1/collections/rr/documents", {"documents": [
            {"id": "old", "title": "半導体 規制 古い", "body": "半導体の輸出規制", "date": "2019-01-01"},
            {"id": "new", "title": "半導体 規制 新しい", "body": "半導体の輸出規制が強化", "date": "2026-06-01"}]})
        st, r = self.c.call("POST", "/api/v1/search", {"q": "半導体", "collections": ["rr"], "date_from": "2025-01-01"})
        self.assertEqual([x["ext_id"] for x in r["results"]], ["new"])
        with mock.patch.object(app.providers, "rerank_enabled", return_value=True), \
                mock.patch.object(app.providers, "rerank", return_value=[(1, 0.9), (0, 0.1)]):
            res = app.searcher.search("半導体", ["rr"])
        self.assertTrue(any(s["stage"] == "rerank" for s in res["trace"]["stages"]))

    def test_analytics(self):
        self.c.call("POST", "/api/v1/collections", {"name": "an", "kind": "patent"})
        self.c.call("POST", "/api/v1/collections/an/documents", {"documents": [
            {"id": "1", "title": "x", "body": "y", "date": "2021-02-01", "source": "EPO", "meta": {"applicants": ["A社"], "ipc": "H01M"}},
            {"id": "2", "title": "x2", "body": "y", "date": "2023-02-01", "source": "EPO", "meta": {"applicants": ["A社", "B社"]}}]})
        st, r = self.c.call("GET", "/api/v1/analytics?collection=an&field=applicants")
        self.assertEqual(r["by_year"], [{"k": "2021", "n": 1}, {"k": "2023", "n": 1}])
        self.assertEqual(r["by_field"][0], {"k": "A社", "n": 2})
        self.assertIn("applicants", r["fields"])
        self.assertTrue(r["matrix"])
        self.assertEqual(self.c.call("GET", "/api/v1/analytics?collection=an&field=bad;drop")[0], 400)

    def test_pc_client_end_to_end(self):
        self.c.call("PUT", "/api/devices/pairing", {"passcode": "client-pass-1"})
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, QNAPLIBRARY_CLIENT_CONF=os.path.join(d, "c.json"), NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
            cli = [sys.executable, str(ROOT / "scripts" / "client" / "qnaplibrary_client.py")]
            data = Path(d) / "docs"
            data.mkdir()
            (data / "memo.md").write_text("# 電池メモ\n全固体電池の課題")
            (data / "recs.ndjson").write_text(json.dumps({"id": "r1", "title": "ドアの特許", "body": "ドア"}, ensure_ascii=False) + "\n")

            def run(*args):
                out = subprocess.run(cli + list(args), env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(out.returncode, 0, out.stderr + out.stdout)
                return out.stdout
            run("pair", "--url", self.srv.base, "--passcode", "client-pass-1", "--name", "pc")
            self.assertIn("完了", run("push", "--collection", "pc-docs", str(data)))
            self.assertIn("embedded", run("embed", "--collection", "pc-docs", "--endpoint", self.fake_url, "--model", "fake", "--truncate", "0"))
            self.assertIn("電池メモ", run("search", "全固体", "--collection", "pc-docs"))
        n = self.srv.app.store.one("SELECT COUNT(*) FROM vectors WHERE model='fake'")[0]
        self.assertGreaterEqual(n, 2)


if __name__ == "__main__":
    unittest.main()
