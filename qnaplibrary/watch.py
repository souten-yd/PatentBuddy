"""Patent / topic watches and the background scheduler.

A watch runs a connector periodically (e.g. EPO OPS CQL weekly), stores the documents and,
when attached to a patent project, ranks the NEW documents against the project's claims so
likely X/Y prior art or infringement candidates surface as "hits". The scheduler also sends
deadline reminders once per threshold. Everything is bounded and runs in one daemon thread;
timers live in RAM, so an idle NAS performs no periodic disk writes.
"""
import json
import logging
import threading
import time

from . import connectors, textproc

LOG = logging.getLogger("qnaplibrary.watch")
TICK_SECONDS = 600
MIN_INTERVAL_HOURS = 6


class Watches:
    def __init__(self, app):
        self.app = app
        self.store = app.store

    def _row(self, r):
        d = dict(r)
        d["params"] = json.loads(d["params"] or "{}")
        d["new_hits"] = self.store.one("SELECT COUNT(*) FROM watch_hits WHERE watch_id=? AND status='new'", (r["id"],))[0]
        return d

    def list(self, patent_id=None):
        if patent_id:
            rows = self.store.q("SELECT * FROM watches WHERE patent_id=? ORDER BY id", (int(patent_id),))
        else:
            rows = self.store.q("SELECT * FROM watches ORDER BY id")
        return [self._row(r) for r in rows]

    def get(self, wid):
        r = self.store.one("SELECT * FROM watches WHERE id=?", (int(wid),))
        if not r:
            raise ValueError("watch not found")
        return self._row(r)

    def create(self, name, connector, params=None, collection="", patent_id=None, interval_hours=168):
        if connector not in [c["id"] for c in connectors.CATALOG]:
            raise ValueError("unknown connector")
        interval = max(MIN_INTERVAL_HOURS, min(int(interval_hours or 168), 24 * 90))
        if patent_id:
            self.app.patents.get(patent_id)
        with self.store.lock:
            cur = self.store.db.execute(
                "INSERT INTO watches(name,patent_id,connector,params,collection,interval_hours,created) VALUES(?,?,?,?,?,?,?)",
                ((name or connector)[:120], int(patent_id) if patent_id else None, connector,
                 json.dumps(params or {}, ensure_ascii=False), (collection or "")[:80], interval, time.time()))
        return self.get(cur.lastrowid)

    def update(self, wid, patch):
        w = self.get(wid)
        fields = {"name": patch.get("name", w["name"]), "params": json.dumps(patch.get("params", w["params"]), ensure_ascii=False),
                  "collection": patch.get("collection", w["collection"]),
                  "interval_hours": max(MIN_INTERVAL_HOURS, int(patch.get("interval_hours", w["interval_hours"]))),
                  "enabled": 1 if patch.get("enabled", bool(w["enabled"])) else 0}
        with self.store.lock:
            self.store.db.execute("UPDATE watches SET name=?, params=?, collection=?, interval_hours=?, enabled=? WHERE id=?",
                                  (fields["name"], fields["params"], fields["collection"], fields["interval_hours"],
                                   fields["enabled"], w["id"]))
        return self.get(w["id"])

    def delete(self, wid):
        with self.store.lock:
            return self.store.db.execute("DELETE FROM watches WHERE id=?", (int(wid),)).rowcount

    def hits(self, wid=None, patent_id=None, status=None, limit=200):
        sql = ("SELECT h.*, d.title, d.ext_id, d.url, d.doc_date, w.name AS watch_name FROM watch_hits h "
               "JOIN documents d ON d.id=h.doc_id JOIN watches w ON w.id=h.watch_id WHERE 1=1")
        args = []
        if wid:
            sql += " AND h.watch_id=?"
            args.append(int(wid))
        if patent_id:
            sql += " AND h.patent_id=?"
            args.append(int(patent_id))
        if status:
            sql += " AND h.status=?"
            args.append(status)
        sql += " ORDER BY h.status='new' DESC, h.score DESC, h.id DESC LIMIT ?"
        return [dict(r) for r in self.store.q(sql, args + [int(limit)])]

    def set_hit(self, hit_id, status, category=None):
        if status not in ("new", "relevant", "dismissed"):
            raise ValueError("status must be new/relevant/dismissed")
        hit = self.store.one("SELECT * FROM watch_hits WHERE id=?", (int(hit_id),))
        if not hit:
            raise ValueError("hit not found")
        with self.store.lock:
            self.store.db.execute("UPDATE watch_hits SET status=? WHERE id=?", (status, int(hit_id)))
        if status == "relevant" and hit["patent_id"]:
            doc = self.store.get_document(hit["doc_id"])
            self.app.patents.add_ref(hit["patent_id"], "%s %s" % (doc.get("ext_id") or "", doc["title"]), doc["id"],
                                     category or "Y", "ウォッチで検出（スコア %.3f）" % hit["score"])
        return {"ok": True}

    # run -------------------------------------------------------------------
    def run(self, wid):
        w = self.get(wid)
        # A saved search expression may contain an unpublished idea. Old
        # watches are intentionally disabled until explicit public-only consent.
        if w.get("params", {}).get("public_only_confirmed") is not True:
            raise ValueError("機密保護: ウォッチの外部検索は公開検索語として明示承認するまで実行できません")
        spec = next(c for c in connectors.CATALOG if c["id"] == w["connector"])
        t0 = time.time()
        status = ""
        new_hits = 0
        try:
            docs = connectors.run(w["connector"], w["params"], self.app.config.secret, self.app.config.get("connectors", default={}))
            coll = self.store.ensure_collection(w["collection"] or "%s-%s" % (spec["kind"], w["connector"]), spec["kind"])
            res = self.store.add_documents(coll["id"], docs, actor="watch:%d" % w["id"])
            new_hits = self._score(w, coll, res["added_ids"])
            status = "ok: 取得 %d / 新規 %d / ヒット %d" % (len(docs), res["added"], new_hits)
        except Exception as error:
            status = "error: %s" % str(error)[:200]
            LOG.warning("watch %s failed: %s", w["id"], error)
        with self.store.lock:
            self.store.db.execute("UPDATE watches SET last_run=?, last_status=? WHERE id=?", (time.time(), status, w["id"]))
        if new_hits:
            self.app.notifier.send("ウォッチ「%s」で新しい候補 %d 件" % (w["name"], new_hits),
                                   "\n".join("- %s %s" % (h["ext_id"] or "", h["title"]) for h in self.hits(w["id"], status="new", limit=10)),
                                   key="watch:%d:%d" % (w["id"], int(t0)))
        return dict(self.get(w["id"]), ms=round((time.time() - t0) * 1000))

    def _score(self, w, coll, added_ids):
        if not added_ids:
            return 0
        added = set(added_ids)
        scores = {}
        if w["patent_id"]:
            project = self.app.patents.get(w["patent_id"])
            text = " ".join([project["title"], self.app.patents.latest_claims(project)[:1500],
                             project["data"].get("solution", "")])
            query = textproc.or_query(text)
            if query:
                res = self.app.searcher.search(query, [coll["id"]], limit=200, mode="hybrid")
                for rank, r in enumerate(res["results"]):
                    if r["doc_id"] in added:
                        scores[r["doc_id"]] = round(1.0 / (1 + rank), 4)
        else:
            scores = {d: 0.0 for d in added}
        t = time.time()
        with self.store.lock:
            for doc_id, score in scores.items():
                self.store.db.execute("INSERT OR IGNORE INTO watch_hits(watch_id,patent_id,doc_id,score,created) VALUES(?,?,?,?,?)",
                                      (w["id"], w["patent_id"], doc_id, score, t))
        return len(scores)

    def due(self):
        t = time.time()
        return [w["id"] for w in self.list()
                if w["enabled"] and w["params"].get("public_only_confirmed") is True
                and (not w["last_run"] or t - w["last_run"] >= w["interval_hours"] * 3600)]


class Scheduler:
    """Runs due watches and the daily deadline reminder from one daemon thread."""

    def __init__(self, app):
        self.app = app
        self._stop = threading.Event()
        self._last_deadline_day = None
        self.status = {"last_tick": None, "last_deadline_check": None}

    def start(self):
        threading.Thread(target=self._loop, name="scheduler", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        self._stop.wait(60)  # let startup finish
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                LOG.exception("scheduler tick failed")
            self._stop.wait(TICK_SECONDS)

    def tick(self):
        self.status["last_tick"] = time.time()
        for wid in self.app.watches.due():
            if self._stop.is_set():
                return
            self.app.watches.run(wid)
        today = time.strftime("%Y-%m-%d")
        if self._last_deadline_day != today:
            self._last_deadline_day = today
            self.deadline_reminders()

    def deadline_reminders(self):
        self.status["last_deadline_check"] = time.time()
        thresholds = sorted(self.app.config.get("notify", "deadline_days", default=[60, 30, 7]) or [], reverse=True)
        sent = 0
        for p in self.app.patents.list():
            full = self.app.patents.get(p["id"])
            for d in full["deadlines"]:
                if d["days_left"] < 0:
                    continue
                hit = [t for t in thresholds if d["days_left"] <= t]
                if not hit:
                    continue
                threshold = min(hit)
                key = "deadline:%d:%s:%s:%d" % (p["id"], d["key"], d["due"], threshold)
                res = self.app.notifier.send("期限 %s（あと%d日）: %s" % (d["due"], d["days_left"], p["title"]),
                                             "%s\n根拠: %s\n※目安です。正式な期限は特許庁の通知・弁理士で確認してください。" % (d["label"], d["basis"]),
                                             key=key)
                sent += sum(1 for r in res if r.get("ok"))
        return sent
