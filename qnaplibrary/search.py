"""Hybrid retrieval: BM25 (FTS5, Japanese bigrams) + optional dense vectors, fused with RRF.

Vectors are kept in RAM (float32 arrays) after the first query and reloaded only when the
store's vector_version changes, so repeated searches cause no disk reads beyond the page cache.
numpy is used when importable; otherwise a pure-Python dot product scans only BM25 candidates
(plus everything when the collection is small).
"""
import math
import threading
import time
from array import array

from . import debuglog, textproc

try:  # optional accelerator
    import numpy as _np  # type: ignore
except Exception:  # pragma: no cover
    _np = None

PURE_PYTHON_FULL_SCAN = 20000


class VectorIndex:
    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._version = -1
        self._ids = []
        self._colls = []
        self._dim = 0
        self._model = ""
        self._mat = None      # numpy matrix (n, dim) normalised, or list of arrays
        self._pos = {}

    def _load(self):
        if self._version == self.store.vector_version:
            return
        rows = self.store.load_vectors()
        ids, colls, vecs, dim, model = [], [], [], 0, ""
        for r in rows:
            if dim and r["dim"] != dim:
                continue  # mixed dims: keep the first model's vectors only
            dim, model = r["dim"], r["model"]
            v = array("f")
            v.frombytes(r["vec"])
            ids.append(r["chunk_id"])
            colls.append(r["collection_id"])
            vecs.append(v)
        if _np is not None and vecs:
            mat = _np.frombuffer(b"".join(v.tobytes() for v in vecs), dtype=_np.float32).reshape(len(vecs), dim)
            norms = _np.linalg.norm(mat, axis=1)
            norms[norms == 0] = 1
            self._mat = mat / norms[:, None]
        else:
            normed = []
            for v in vecs:
                n = math.sqrt(sum(x * x for x in v)) or 1.0
                normed.append(array("f", (x / n for x in v)))
            self._mat = normed
        self._ids, self._colls, self._dim, self._model = ids, colls, dim, model
        self._pos = {cid: i for i, cid in enumerate(ids)}
        self._version = self.store.vector_version

    def info(self):
        with self._lock:
            self._load()
            return {"vectors": len(self._ids), "dim": self._dim, "model": self._model,
                    "numpy": _np is not None, "ram_mb": round(len(self._ids) * self._dim * 4 / 1048576, 1)}

    def search(self, qvec, collection_ids=None, limit=50, candidates=None):
        with self._lock:
            self._load()
            if not self._ids or not qvec or len(qvec) != self._dim:
                return []
            qn = math.sqrt(sum(x * x for x in qvec)) or 1.0
            q = [x / qn for x in qvec]
            allowed = set(collection_ids) if collection_ids else None
            if _np is not None:
                scores = self._mat @ _np.asarray(q, dtype=_np.float32)
                idx = range(len(self._ids))
                pairs = [(self._ids[i], float(scores[i])) for i in idx
                         if allowed is None or self._colls[i] in allowed]
            else:
                if candidates is not None and len(self._ids) > PURE_PYTHON_FULL_SCAN:
                    idx = [self._pos[c] for c in candidates if c in self._pos]
                else:
                    idx = range(len(self._ids))
                pairs = []
                for i in idx:
                    if allowed is not None and self._colls[i] not in allowed:
                        continue
                    v = self._mat[i]
                    pairs.append((self._ids[i], sum(a * b for a, b in zip(v, q))))
            pairs.sort(key=lambda p: -p[1])
            return pairs[:limit]


def rrf(rankings, k=60):
    scores = {}
    for ranking in rankings:
        for rank, (cid, _s) in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda p: -p[1])


class Searcher:
    def __init__(self, store, config, embedder=None):
        self.store = store
        self.config = config
        self.vectors = VectorIndex(store)
        self.embedder = embedder  # callable(list[str]) -> list[list[float]] or None

    def search(self, query, collections=None, limit=20, mode="hybrid", group_by_doc=True, qvec=None):
        t0 = time.time()
        trace = {"query": query, "mode": mode, "stages": []}
        coll_ids = None
        if collections:
            coll_ids = [self.store.get_collection(c)["id"] for c in collections]
        limit = max(1, min(int(limit or 20), 200))
        pool = max(limit * 5, 50)
        bm25 = self.store.fts_search(query, coll_ids, pool) if mode in ("hybrid", "keyword") else []
        trace["stages"].append({"stage": "bm25", "hits": len(bm25), "ms": round((time.time() - t0) * 1000, 1)})
        dense = []
        if mode in ("hybrid", "vector"):
            if qvec is None and self.embedder is not None:
                try:
                    t1 = time.time()
                    vecs = self.embedder([query], query=True)
                    qvec = vecs[0] if vecs else None
                    if qvec is not None:
                        trace["stages"].append({"stage": "embed", "ms": round((time.time() - t1) * 1000, 1)})
                except Exception as error:  # embedding is optional
                    trace["stages"].append({"stage": "embed", "error": str(error)[:200]})
                    qvec = None
            if qvec:
                t2 = time.time()
                dense = self.vectors.search(qvec, coll_ids, pool, candidates=[c for c, _ in bm25])
                trace["stages"].append({"stage": "vector", "hits": len(dense), "ms": round((time.time() - t2) * 1000, 1)})
        if bm25 and dense:
            fused = rrf([bm25, dense], self.config.get("search", "rrf_k", default=60))
        else:
            fused = bm25 or dense
        rows = self.store.chunks_with_docs([c for c, _ in fused[:pool]])
        terms = textproc.query_terms(query)
        results, seen = [], {}
        for cid, score in fused:
            r = rows.get(cid)
            if r is None:
                continue
            if group_by_doc and r["did"] in seen:
                seen[r["did"]]["more_chunks"] += 1
                continue
            item = {"chunk_id": cid, "doc_id": r["did"], "score": round(score, 5), "title": r["title"],
                    "collection": r["collection"], "collection_id": r["collection_id"], "section": r["section"],
                    "ext_id": r["ext_id"], "url": r["url"], "date": r["doc_date"], "source": r["source"],
                    "snippet": textproc.snippet(r["text"], terms), "text": r["text"], "more_chunks": 0}
            results.append(item)
            seen[r["did"]] = item
            if len(results) >= limit:
                break
        trace["results"] = len(results)
        trace["ms"] = round((time.time() - t0) * 1000, 1)
        trace["ts"] = time.time()
        debuglog.note_search(trace)
        return {"results": results, "trace": trace}
