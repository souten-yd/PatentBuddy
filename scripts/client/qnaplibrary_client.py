#!/usr/bin/env python3
"""QnapLibrary PC client (Python 3.8+, standard library only).

  python3 qnaplibrary_client.py pair   --url http://NAS:17871 --passcode XXXX --name my-pc
  python3 qnaplibrary_client.py push   --collection patents-jp --kind patent ./folder_or_files ...
  python3 qnaplibrary_client.py embed  --collection patents-jp --endpoint http://localhost:11434/v1 --model qwen3-embedding:0.6b
  python3 qnaplibrary_client.py search "固体電解質 電池" --collection patents-jp

push: .ndjson/.jsonl/.json/.csv are imported as records; .txt/.md become one document each (id = relative path);
      .pdf is converted with `pdftotext` (poppler) or the `pypdf` module when available (OCR is not done here).
embed: computes embeddings on this PC (Ollama / llama.cpp / vLLM / any OpenAI-compatible /embeddings) for chunks
       that have none yet and stores them on the NAS. Use the same model on the NAS (設定 > AI > 埋め込み) so that
       queries are embedded in the same space.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONF = Path(os.environ.get("QNAPLIBRARY_CLIENT_CONF", Path.home() / ".config" / "qnaplibrary" / "client.json"))
RECORD_EXT = {".ndjson": "ndjson", ".jsonl": "ndjson", ".json": "json", ".csv": "csv"}
TEXT_EXT = {".txt", ".md", ".markdown"}


def load_conf():
    try:
        return json.loads(CONF.read_text())
    except (OSError, ValueError):
        sys.exit("未ペアリングです。先に pair を実行してください")


def call(conf, method, path, body=None, timeout=300):
    req = urllib.request.Request(conf["url"].rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + conf.get("token", "")})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        sys.exit("HTTP %d: %s" % (error.code, error.read(500).decode("utf-8", "replace")))


def cmd_pair(a):
    conf = {"url": a.url.rstrip("/")}
    r = call(dict(conf, token=""), "POST", "/api/v1/pair", {"passcode": a.passcode, "name": a.name, "scopes": a.scopes})
    conf["token"] = r["token"]
    CONF.parent.mkdir(parents=True, exist_ok=True)
    CONF.write_text(json.dumps(conf))
    os.chmod(str(CONF), 0o600)
    print("ペアリングしました: %s（設定: %s）" % (r["name"], CONF))


def pdf_text(path):
    if shutil.which("pdftotext"):
        out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=300)
        if out.returncode == 0:
            return out.stdout.decode("utf-8", "replace")
    try:
        import pypdf  # type: ignore
        return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages)
    except ImportError:
        return None


def iter_files(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    yield f, f.relative_to(p)
        elif p.is_file():
            yield p, Path(p.name)


def ensure_collection(conf, name, kind):
    cols = {c["name"] for c in call(conf, "GET", "/api/v1/collections")["collections"]}
    if name not in cols:
        call(conf, "POST", "/api/v1/collections", {"name": name, "kind": kind})


def cmd_push(a):
    conf = load_conf()
    ensure_collection(conf, a.collection, a.kind)
    coll = urllib.parse.quote(a.collection)
    batch, total = [], {"added": 0, "updated": 0, "unchanged": 0}

    def flush():
        if batch:
            r = call(conf, "POST", "/api/v1/collections/%s/documents" % coll, {"documents": batch})
            for k in total:
                total[k] += r[k]
            batch.clear()
    for f, rel in iter_files(a.paths):
        ext = f.suffix.lower()
        if ext in RECORD_EXT:
            flush()
            r = call(conf, "POST", "/api/v1/collections/%s/import" % coll,
                     {"format": RECORD_EXT[ext], "data": f.read_text(encoding="utf-8", errors="replace")})
            for k in total:
                total[k] += r[k]
            print("records", rel, r)
            continue
        if ext in TEXT_EXT:
            text = f.read_text(encoding="utf-8", errors="replace")
        elif ext == ".pdf":
            text = pdf_text(f)
            if text is None:
                print("skip (pdftotext / pypdf が必要):", rel)
                continue
        else:
            continue
        batch.append({"id": str(rel).replace(os.sep, "/"), "title": f.stem, "body": text, "source": a.source or "pc-client",
                      "meta": {"file": str(rel), "bytes": f.stat().st_size}})
        if len(batch) >= 100:
            flush()
    flush()
    print("完了:", total)


def cmd_embed(a):
    conf = load_conf()
    info = call(conf, "GET", "/api/v1/embedding-info")
    trunc = a.truncate if a.truncate is not None else (info.get("truncate_dim") or 0)
    tag = a.model + ("@%d" % trunc if trunc else "")
    if info.get("model_tag") and info["model_tag"] != tag:
        print("注意: NAS の検索用埋め込み (%s) と異なる空間 (%s) です。NAS 側も同じモデルに設定してください。" % (info["model_tag"], tag))
    coll = urllib.parse.quote(a.collection)
    done = 0
    while True:
        chunks = call(conf, "GET", "/api/v1/collections/%s/pending-chunks?limit=%d&model=%s" % (coll, a.batch, urllib.parse.quote(tag)))["chunks"]
        if not chunks:
            break
        body = {"model": a.model, "input": [(info.get("doc_prefix") or "") + c["title"] + "\n" + c["text"] for c in chunks]}
        headers = {"Content-Type": "application/json"}
        if a.api_key:
            headers["Authorization"] = "Bearer " + a.api_key
        req = urllib.request.Request(a.endpoint.rstrip("/") + "/embeddings", data=json.dumps(body).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read())["data"]
        vecs = [d["embedding"][:trunc] if trunc else d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]
        call(conf, "POST", "/api/v1/vectors", {"model": tag, "items": [{"chunk_id": c["chunk_id"], "vector": v} for c, v in zip(chunks, vecs)]})
        done += len(chunks)
        print("embedded", done)
    print("完了:", done)


def cmd_search(a):
    conf = load_conf()
    r = call(conf, "POST", "/api/v1/search", {"q": a.query, "collections": [a.collection] if a.collection else None, "limit": a.limit})
    for x in r["results"]:
        print("%-24s %s [%s %s]\n    %s" % (x.get("ext_id") or x["doc_id"], x["title"], x["collection"], x["section"], x["snippet"][:160]))


def main():
    ap = argparse.ArgumentParser(description="QnapLibrary PC client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair")
    p.add_argument("--url", required=True)
    p.add_argument("--passcode", required=True)
    p.add_argument("--name", default=os.uname().nodename if hasattr(os, "uname") else "pc")
    p.add_argument("--scopes", default="rw", choices=["rw", "ro"])
    p = sub.add_parser("push")
    p.add_argument("--collection", required=True)
    p.add_argument("--kind", default="generic")
    p.add_argument("--source", default="")
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("embed")
    p.add_argument("--collection", required=True)
    p.add_argument("--endpoint", required=True, help="OpenAI 互換 /v1（例: http://localhost:11434/v1）")
    p.add_argument("--model", required=True)
    p.add_argument("--api-key", default=os.environ.get("EMBED_API_KEY", ""))
    p.add_argument("--truncate", type=int, default=None)
    p.add_argument("--batch", type=int, default=64)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--collection", default="")
    p.add_argument("--limit", type=int, default=10)
    a = ap.parse_args()
    {"pair": cmd_pair, "push": cmd_push, "embed": cmd_embed, "search": cmd_search}[a.cmd](a)


if __name__ == "__main__":
    main()
