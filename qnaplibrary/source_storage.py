"""Read-only storage accounting and explicit source budget settings.

The soft budget applies to new scoped collection operations, not pre-existing
import/watch paths. Filesystem observations are snapshots, not hard guarantees.
"""
import json
from pathlib import Path
import shutil

POLICY_KEY = "source_budget_v1"
DEFAULT_POLICY = {
    "soft_limit_mib": 5120,
    "max_results_per_fetch": 25,
    "max_figures_per_pdf": 12,
    "allow_scheduled_collection": False,
}


def validate_policy(data):
    if not isinstance(data, dict) or set(data) != set(DEFAULT_POLICY):
        raise ValueError("すべての容量設定を指定してください")
    for key, low, high in (("soft_limit_mib", 128, 1048576),
                           ("max_results_per_fetch", 1, 25),
                           ("max_figures_per_pdf", 0, 200)):
        value = data[key]
        if type(value) is not int or not low <= value <= high:
            raise ValueError(key + " が範囲外です")
    if type(data["allow_scheduled_collection"]) is not bool:
        raise ValueError("自動取得は真偽値で指定してください")
    # Scheduling stays disabled pending a separate privacy / quota review.
    if data["allow_scheduled_collection"]:
        raise ValueError("分類別の自動収集はまだ許可されていません")
    return dict(data)


def policy(store):
    row = store.one("SELECT value FROM meta WHERE key=?", (POLICY_KEY,))
    if not row:
        return dict(DEFAULT_POLICY)
    try:
        return validate_policy(json.loads(row[0]))
    except (ValueError, TypeError):
        raise ValueError("保存済みの取得容量設定が不正です") from None


def save_policy(store, data):
    checked = validate_policy(data)
    value = json.dumps(checked, separators=(",", ":"))
    with store.tx() as db:
        db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (POLICY_KEY, value))
    return checked


def usage(store, *, include_counts=False):
    """Stat allocated files; never scan BLOB contents or read source PDFs."""
    path = Path(store.path)
    files = {}
    for name, file in (("sqlite", path), ("wal", Path(str(path) + "-wal")),
                       ("shm", Path(str(path) + "-shm"))):
        try:
            size = file.stat().st_size if file.is_file() else 0
        except OSError:
            size = 0
        files[name + "_bytes"] = size
    disk = shutil.disk_usage(path.parent)
    limit = policy(store)["soft_limit_mib"] * 1024 * 1024
    size = files["sqlite_bytes"] + files["wal_bytes"] + files["shm_bytes"]
    result = {
        "files": files, "total_database_files_bytes": size,
        "disk_free_bytes": disk.free, "disk_total_bytes": disk.total,
        "soft_limit_bytes": limit, "soft_limit_reached": size >= limit,
        "notes": [
            "SQLite・WAL・SHMの実ファイルサイズです。論理データ量の合計ではありません。",
            "画像とPDFは既存SQLite内に保管されており重複加算しません。",
            "現在の上限は次期の収集処理用ソフト上限で、既存の全取り込み経路を停止しません。",
            "物理ディスク空き容量と新規書き込み可能量は同一ではありません。",
        ],
        "read_only": True,
    }
    if include_counts:
        # Explicitly requested count: may read indexes for large corpora.
        result["counts"] = {
            "documents": store.one("SELECT count(*) FROM documents")[0],
            "pdf_originals": store.one("SELECT count(*) FROM source_pdfs")[0],
            "pdf_images": store.one("SELECT count(*) FROM pdf_image_blobs")[0],
        }
    return result
