#!/usr/bin/env python3
"""Offline and opt-in SQLite ingestion/search benchmark for QnapPatentBuddy.

Always creates a fresh temporary database; never touches the user's existing
QNAP library. Values are synthetic, not a guarantee of real patent performance.
"""
import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qnaplibrary.store import Store

SAMPLE = ("固体電解質を含む蓄電装置において、正極および負極の間に"
          "硫化物系電解質層を設ける。充放電特性と安全性を改善する。")


def _ms(fn, repeats=30):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return {"p50_ms": round(statistics.median(samples), 2),
            "p95_ms": round(samples[min(len(samples)-1, int(len(samples)*0.95))], 2),
            "max_ms": round(samples[-1], 2)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=int, default=1000, help="1..100000 synthetic patent records")
    parser.add_argument("--batch", type=int, default=200, help="1..1000 documents per transaction")
    parser.add_argument("--workdir", help="temporary directory parent (must have enough disk space)")
    opts = parser.parse_args()
    if not 1 <= opts.documents <= 100000 or not 1 <= opts.batch <= 1000:
        parser.error("documents must be 1..100000 and batch 1..1000")
    with tempfile.TemporaryDirectory(prefix="qpb-bench-", dir=opts.workdir) as root:
        st = Store(Path(root) / "bench.sqlite3")
        try:
            cid = st.create_collection("benchmark-patents", "patent")["id"]
            added, chunks, updates = 0, 0, 0
            t0 = time.perf_counter()
            for start in range(0, opts.documents, opts.batch):
                docs = [{"id": "JP%08dA" % i, "title": "特許公開公報 固体電解質 %d" % i,
                         "body": SAMPLE * 8, "date": "2025-01-01",
                         "meta": {"ipc": ["H01M"], "applicants": ["評価用"]}}
                        for i in range(start, min(start + opts.batch, opts.documents))]
                result = st.add_documents(cid, docs)
                added += result["added"]
                chunks += result["updated"]
            seconds = time.perf_counter() - t0
            before = st.db.total_changes
            t1 = time.perf_counter()
            for start in range(0, opts.documents, opts.batch):
                docs = [{"id": "JP%08dA" % i, "title": "特許公開公報 固体電解質 %d" % i,
                         "body": SAMPLE * 8, "date": "2025-01-01",
                         "meta": {"ipc": ["H01M"], "applicants": ["評価用"]}}
                        for i in range(start, min(start + opts.batch, opts.documents))]
                st.add_documents(cid, docs)
            unchanged_secs = time.perf_counter() - t1
            no_op_writes = st.db.total_changes - before
            initial = st.list_documents(cid, limit=50, cursor="start")
            follow = initial["next_cursor"]
            cursor_perf = _ms(lambda: st.list_documents(cid, limit=50, cursor=follow or "start"))
            search_perf = _ms(lambda: st.fts_search("固体電解質", [cid], limit=20), repeats=10)
            db_file = Path(root) / "bench.sqlite3"
            result = {
                "synthetic_documents": opts.documents,
                "created": added, "changed_existing": chunks, "fts5": st.fts,
                "ingest_s": round(seconds, 3),
                "ingest_documents_per_s": round(added / seconds, 1) if seconds else None,
                "identical_reingest_s": round(unchanged_secs, 3),
                "identical_reingest_sqlite_row_changes": no_op_writes,
                "cursor_listing": cursor_perf, "keyword_search": search_perf,
                "db_bytes": db_file.stat().st_size,
                "notes": "Synthetic, measured on this host; not an estimate for TS-253Be",
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            st.close()


if __name__ == "__main__":
    main()
