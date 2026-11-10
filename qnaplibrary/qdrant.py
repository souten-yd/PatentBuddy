"""Optional Qdrant backend for vector search (Container Station / another host).

SQLite stays the source of truth: vectors are always stored there; Qdrant is a mirror index used
for search when `vector_backend.type == "qdrant"`. Points carry payload {collection_id, model}
so searches filter by library collection and embedding space. Stale points (deleted chunks)
are dropped at read time because results are joined against SQLite.
"""
import json
import logging
import urllib.error
import urllib.request

from .llm import _DIRECT_OPENER
from .privacy import local_endpoint

LOG = logging.getLogger("qnaplibrary.qdrant")


class QdrantError(RuntimeError):
    pass


class Qdrant:
    def __init__(self, url, collection="qnaplibrary", api_key=None, timeout=30):
        self.url = url.rstrip("/")
        self.collection = collection
        self.api_key = api_key
        self.timeout = timeout
        self._ready_dim = None

    def _call(self, method, path, body=None):
        if not local_endpoint(self.url):
            # Remote mirrors must be individually approved at the App boundary,
            # but never permit redirects or environment-configured proxies.
            raise QdrantError("機密保護: 信頼できないQdrant送信先です")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers, method=method)
        try:
            with _DIRECT_OPENER.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as error:
            if error.code == 404 and method == "GET":
                return None
            raise QdrantError("Qdrant %s %s: HTTP %d %s" % (method, path, error.code, error.read(300).decode("utf-8", "replace")))
        except (urllib.error.URLError, OSError) as error:
            raise QdrantError("Qdrant に接続できません: %s" % getattr(error, "reason", error))

    def info(self):
        data = self._call("GET", "/collections/%s" % self.collection)
        if not data:
            return {"exists": False}
        r = data.get("result", {})
        return {"exists": True, "points": r.get("points_count"), "status": r.get("status"),
                "dim": (((r.get("config") or {}).get("params") or {}).get("vectors") or {}).get("size")}

    def ensure(self, dim, recreate=False):
        if self._ready_dim == dim and not recreate:
            return
        info = self.info()
        if info["exists"] and (recreate or info.get("dim") != dim):
            self._call("DELETE", "/collections/%s" % self.collection)
            info = {"exists": False}
        if not info["exists"]:
            self._call("PUT", "/collections/%s" % self.collection,
                       {"vectors": {"size": dim, "distance": "Cosine"}, "on_disk_payload": True})
            for field in ("collection_id", "model"):
                self._call("PUT", "/collections/%s/index" % self.collection,
                           {"field_name": field, "field_schema": "integer" if field == "collection_id" else "keyword"})
        self._ready_dim = dim

    def upsert(self, rows):
        """rows: [(chunk_id, collection_id, model, vector)]"""
        if not rows:
            return 0
        self.ensure(len(rows[0][3]))
        points = [{"id": int(cid), "vector": [float(x) for x in vec], "payload": {"collection_id": int(coll), "model": model}}
                  for cid, coll, model, vec in rows]
        for i in range(0, len(points), 256):
            self._call("PUT", "/collections/%s/points?wait=true" % self.collection, {"points": points[i:i + 256]})
        return len(points)

    def search(self, vector, collection_ids=None, model=None, limit=50):
        must = []
        if collection_ids:
            must.append({"key": "collection_id", "match": {"any": [int(c) for c in collection_ids]}})
        if model:
            must.append({"key": "model", "match": {"value": model}})
        body = {"vector": [float(x) for x in vector], "limit": int(limit), "with_payload": False}
        if must:
            body["filter"] = {"must": must}
        data = self._call("POST", "/collections/%s/points/search" % self.collection, body)
        return [(int(p["id"]), float(p["score"])) for p in (data or {}).get("result", [])]
