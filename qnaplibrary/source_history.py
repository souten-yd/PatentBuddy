"""Source acquisition receipts and bounded per-source storage sampling.

Physical bytes cannot be attributed accurately to individual SQLite rows, so
only the total SQLite/WAL/SHM file size is physical. By-source bytes below are
bounded, logical payload estimates from the newest documents, not disk usage.
"""
import time

ALLOWED_STATUSES = frozenset(("running", "succeeded", "failed"))
MAX_HISTORY = 50
MAX_SAMPLE = 5000


def start(store, source, code, requested, *, scope=None):
    """Record a bounded, public IPC scope only; never persist private search text."""
    from .source_scope import build_scope
    scope = scope or build_scope(ipc=code, limit=requested)
    if (source != "epo_ops" or scope["ipc"] != code
            or scope["limit"] != requested or type(requested) is not int
            or not 1 <= requested <= 25):
        raise ValueError("取得ソースまたは分類が不正です")
    # Revalidate all persisted fields so callers cannot forge the run history.
    checked = build_scope(ipc=code, publication_country=scope["publication_country"],
                          year_from=scope["publication_year_from"],
                          year_to=scope["publication_year_to"],
                          first=scope["first_result"], limit=requested)
    with store.tx() as db:
        cursor = db.execute(
            "INSERT INTO source_acquisition_runs("
            "source,classification,publication_country,publication_year_from,"
            "publication_year_to,first_result,requested,status,started) "
            "VALUES(?,?,?,?,?,?,?,'running',?)",
            (source, code, checked["publication_country"], checked["publication_year_from"],
             checked["publication_year_to"], checked["first_result"], requested, time.time()))
        return cursor.lastrowid


def finish(store, receipt_id, status, *, received=0, added=0, response_bytes=0, failure=""):
    if status not in ("succeeded", "failed"):
        raise ValueError("完了状態が不正です")
    if (any(type(n) is not int or n < 0 for n in (received, added, response_bytes))
            or added > received or response_bytes > 1024 * 1024):
        raise ValueError("取得数/サイズが不正です")
    # Fixed enum only: never log a raw provider response, key, URL, or secret.
    if failure not in ("", "provider_error", "storage_error", "limit_error"):
        raise ValueError("失敗理由は固定コードのみです")
    with store.tx() as db:
        cursor = db.execute(
            "UPDATE source_acquisition_runs SET status=?,finished=?,received=?,added=?,"
            "response_bytes=?,failure_code=? WHERE id=? AND status='running'",
            (status, time.time(), received, added, response_bytes, failure, receipt_id))
        if cursor.rowcount != 1:
            raise ValueError("取得履歴の状態が更新できません")


def list_recent(store, limit=30):
    if type(limit) is not int or not 1 <= limit <= MAX_HISTORY:
        raise ValueError("履歴は1〜50件にしてください")
    rows = store.q(
        "SELECT id,source,classification,publication_country,publication_year_from,"
        "publication_year_to,first_result,requested,received,added,response_bytes,"
        "status,started,finished,failure_code "
        "FROM source_acquisition_runs ORDER BY id DESC LIMIT ?", (limit,))
    now = time.time()
    result = [dict(r) for r in rows]
    for row in result:
        # Display-only interruption hint after a crash; never rewrite audit
        # history or silently claim the run succeeded.
        row["possibly_interrupted"] = (row["status"] == "running" and
                                       now - float(row["started"]) > 600)
    return result


def by_source_sample(store, limit=2000):
    """Read metadata lengths only, over at most limit+1 documents (newest first)."""
    if type(limit) is not int or not 1 <= limit <= MAX_SAMPLE:
        raise ValueError("標本上限は1〜5000件にしてください")
    rows = store.q(
        "SELECT source, length(CAST(title AS BLOB)) AS title_bytes,"
        "length(CAST(meta AS BLOB)) AS meta_bytes,"
        "length(CAST(body AS BLOB)) AS body_bytes "
        "FROM documents ORDER BY id DESC LIMIT ?", (limit + 1,))
    partial = len(rows) > limit
    groups = {}
    for row in rows[:limit]:
        source = str(row["source"] or "(unspecified)")[:100]
        item = groups.setdefault(source, {"source": source, "documents_in_sample": 0,
                                          "logical_payload_bytes_in_sample": 0})
        item["documents_in_sample"] += 1
        item["logical_payload_bytes_in_sample"] += sum(int(row[k] or 0)
                                                       for k in ("title_bytes", "meta_bytes", "body_bytes"))
    # Never hide the limit: rows outside the sample may change rankings.
    return {"scope": "newest_documents_bounded_sample", "documents_examined": min(limit, len(rows)),
            "has_older_documents": partial, "not_physical_storage": True,
            "items": sorted(groups.values(), key=lambda x: (-x["documents_in_sample"], x["source"]))[:30]}
