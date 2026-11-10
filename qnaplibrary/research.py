"""Research jobs ("deep research" over the library, bounded).

question -> LLM plans up to 6 sub-questions -> library search for each (+ optional GDELT news)
-> LLM writes a cited Markdown report -> saved as a document in the `reports` collection.
One job runs at a time in a background thread; progress is kept in the jobs table.
"""
import json
import logging
import re
import threading
import time

from . import connectors

LOG = logging.getLogger("qnaplibrary.research")
MAX_SUBQ = 6
PER_QUERY = 6
MAX_EVIDENCE = 30

PLAN_PROMPT = """次の調査依頼を、ライブラリ検索で答えるためのサブ質問に分解してください。
出力は JSON のみ: {"sub_questions": ["...", ...], "news_query_en": "英語のニュース検索語（不要なら空）"}
サブ質問は最大 %d 個、それぞれ検索しやすい具体的な日本語にしてください。

調査依頼: %s"""

REPORT_PROMPT = """あなたは調査アナリストです。下の「根拠」だけを使って、調査依頼に答える日本語のレポートを Markdown で書いてください。
- 構成: 要約（3〜5行）→ 論点ごとの節 → 不確実な点・追加で調べるべきこと
- 事実には必ず根拠番号 [n] を付ける。根拠に無いことは「根拠なし（一般知識）」と明記する
- 特許・規格・市場など出典の種類の違いに注意する

# 調査依頼
%s

# 根拠
%s"""


class Research:
    def __init__(self, app):
        self.app = app
        self._lock = threading.Lock()
        self._busy = False

    def _save(self, jid, **fields):
        row = self.app.store.one("SELECT params, result FROM jobs WHERE id=?", (jid,))
        result = json.loads(row["result"] or "{}") if row and row["result"] else {}
        result.update(fields.pop("result", {}))
        sets = ["result=?"]
        args = [json.dumps(result, ensure_ascii=False)]
        for k, v in fields.items():
            sets.append("%s=?" % k)
            args.append(v)
        with self.app.store.lock:
            self.app.store.db.execute("UPDATE jobs SET %s WHERE id=?" % ", ".join(sets), args + [jid])

    def start(self, question, collections=None, provider=None, use_news=False):
        question = (question or "").strip()
        if not question:
            raise ValueError("question が必要です")
        with self._lock:
            if self._busy:
                raise ValueError("別の調査ジョブが実行中です。終わってから実行してください")
            self._busy = True
        params = {"question": question[:2000], "collections": collections or [], "provider": provider, "use_news": bool(use_news)}
        with self.app.store.lock:
            cur = self.app.store.db.execute("INSERT INTO jobs(kind,params,status,result,created) VALUES('research',?,?,?,?)",
                                            (json.dumps(params, ensure_ascii=False), "running", json.dumps({"step": "計画中"}), time.time()))
        jid = cur.lastrowid
        threading.Thread(target=self._run, args=(jid, params), daemon=True).start()
        return self.get(jid)

    def get(self, jid):
        r = self.app.store.one("SELECT * FROM jobs WHERE id=? AND kind='research'", (int(jid),))
        if not r:
            raise ValueError("job not found")
        return {"id": r["id"], "status": r["status"], "params": json.loads(r["params"]), "result": json.loads(r["result"] or "{}"),
                "created": r["created"], "finished": r["finished"]}

    def list(self, limit=30):
        return [{"id": r["id"], "status": r["status"], "question": json.loads(r["params"]).get("question"), "created": r["created"],
                 "finished": r["finished"]} for r in self.app.store.q(
                     "SELECT id, status, params, created, finished FROM jobs WHERE kind='research' ORDER BY id DESC LIMIT ?", (int(limit),))]

    def _run(self, jid, p):
        try:
            prov = self.app.providers
            plan_raw = prov.chat([{"role": "user", "content": PLAN_PROMPT % (MAX_SUBQ, p["question"])}], p.get("provider"),
                                 {"temperature": 0.2})["content"]
            plan = _json(plan_raw)
            subqs = [s for s in (plan.get("sub_questions") or []) if isinstance(s, str) and s.strip()][:MAX_SUBQ] or [p["question"]]
            self._save(jid, result={"step": "検索中", "sub_questions": subqs})
            evidence, seen = [], set()
            colls = p.get("collections") or None
            for q in [p["question"]] + subqs:
                for r in self.app.searcher.search(q, colls, PER_QUERY)["results"]:
                    if r["chunk_id"] not in seen and len(evidence) < MAX_EVIDENCE:
                        seen.add(r["chunk_id"])
                        evidence.append(r)
            news_q = (plan.get("news_query_en") or "").strip()
            if p.get("use_news") and news_q:
                try:
                    docs = connectors.gdelt(news_q, "1m", 25)
                    coll = self.app.store.ensure_collection("news-research", "news")
                    self.app.store.add_documents(coll["id"], docs, actor="research")
                    for r in self.app.searcher.search(news_q, [coll["id"]], 8)["results"]:
                        if r["chunk_id"] not in seen and len(evidence) < MAX_EVIDENCE + 8:
                            seen.add(r["chunk_id"])
                            evidence.append(r)
                except Exception as error:
                    LOG.warning("research news step failed: %s", error)
            self._save(jid, result={"step": "執筆中", "evidence": len(evidence)})
            ev_text = "\n\n".join("[%d] %s（%s %s %s）\n%s" % (i + 1, e["title"], e["collection"], e.get("ext_id") or "",
                                                              e.get("date") or "", e["text"][:1000]) for i, e in enumerate(evidence))
            report = prov.chat([{"role": "user", "content": REPORT_PROMPT % (p["question"], ev_text or "（ライブラリに該当なし）")}],
                               p.get("provider"), timeout=300)
            sources = [{"n": i + 1, "doc_id": e["doc_id"], "title": e["title"], "ext_id": e.get("ext_id"), "collection": e["collection"],
                        "url": e.get("url")} for i, e in enumerate(evidence)]
            coll = self.app.store.ensure_collection("reports", "report", "調査ジョブのレポート")
            body = report["content"] + "\n\n## 根拠\n" + "\n".join("[%d] %s %s（%s）" % (s["n"], s["ext_id"] or "", s["title"], s["collection"]) for s in sources)
            saved = self.app.store.add_documents(coll["id"], [{"id": "research-%d" % jid, "title": "調査: " + p["question"][:80],
                                                               "body": body, "source": "research", "date": time.strftime("%Y-%m-%d"),
                                                               "meta": {"job": jid, "model": report.get("model"), "sources": sources}}], actor="research")
            self._save(jid, status="done", finished=time.time(),
                       result={"step": "完了", "report": report["content"], "sources": sources, "doc_id": saved["ids"][0],
                               "model": report.get("model")})
            self.app.notifier.send("調査ジョブ完了: " + p["question"][:60], report["content"][:1500], key="research:%d" % jid)
        except Exception as error:
            LOG.warning("research job %s failed: %s", jid, error)
            self._save(jid, status="failed", finished=time.time(), result={"step": "失敗", "error": str(error)[:400]})
        finally:
            with self._lock:
                self._busy = False


def _json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}
