"""USPTO ODP bulk-dataset file catalogue: manual, bounded, no downloads.

Technique adapted from the documented API contract in pyUSPTO (MIT, with
credit in docs). Only call the fixed official ODP endpoint after an admin
explicitly requests the preview. No arbitrary URLs, remote file execution,
archive extraction, cron, webhook, or Autonomous ControlDeck capabilities.
"""
import datetime as dt
import json
import re
import urllib.parse

from . import connectors

ODP_BASE = "https://api.uspto.gov/api/v1/datasets/products/"
PRODUCTS = {
    # ODP product IDs documented by pyUSPTO and USPTO Bulk Data Directory.
    "PTGRXML": "Patent Grant Full-Text Data (No Images), XML",
    "PTFWPRD": "Patent File Wrapper Daily, JSON delta",
    "PTFWPRE": "Patent File Wrapper Weekly, JSON",
}
MAX_LIST = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PREVIEW_BYTES = 512 * 1024 * 1024  # advisory only; no files downloaded
SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
ISO_DATE = re.compile(r"^[12][0-9]{3}-[01][0-9]-[0-3][0-9]$")


def check_dates(start, end):
    """The catalogue may be queried without dates or with a bounded window."""
    if (start is None) != (end is None):
        raise ValueError("取得日付の開始と終了は両方指定してください")
    if start is None:
        return None, None
    if not all(type(d) is str and ISO_DATE.fullmatch(d) for d in (start, end)):
        raise ValueError("日付はYYYY-MM-DDで指定してください")
    try:
        first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    except ValueError:
        raise ValueError("存在しない日付です") from None
    if (first > last or (last - first).days > 366 or
            last > dt.date.today()):
        raise ValueError("公開データの範囲は366日以内で指定してください")
    return start, end


def normalize_payload(raw, product_id, limit):
    """Validate ODP response before showing file identity or size to the user.

    Never return a fileDownloadURI from untrusted provider JSON. A follow-up
    download implementation must request only official endpoint IDs and recheck
    its URL, expected byte size, free space and the content hash.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("USPTOファイル一覧の応答が大きすぎます")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ValueError("USPTOファイル一覧のJSONが不正です") from None
    if not isinstance(data, dict):
        raise ValueError("USPTOファイル一覧が不正です")
    products = data.get("bulkDataProductBag")
    if not isinstance(products, list) or len(products) != 1 or not isinstance(products[0], dict):
        raise ValueError("USPTOのバルク製品応答が不正です")
    product = products[0]
    if product.get("productIdentifier") != product_id:
        raise ValueError("指定以外のUSPTO製品が返りました")
    bag = product.get("productFileBag") or {}
    if not isinstance(bag, dict) or not isinstance(bag.get("fileDataBag"), list):
        raise ValueError("USPTOファイル明細がありません")
    entries = bag["fileDataBag"]
    if len(entries) > limit:
        raise ValueError("要求件数を超える明細が返りました")
    files = []
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("USPTOファイル明細が不正です")
        name, size = item.get("fileName"), item.get("fileSize")
        if (type(name) is not str or not SAFE_FILE.fullmatch(name)
                or name in (".", "..") or type(size) is not int or
                not 0 < size <= 2**50):
            raise ValueError("USPTOファイル名かサイズが不正です")
        files.append({
            "file_name": name,
            "bytes": size,
            "format": str(item.get("fileTypeText") or "")[:60],
            "data_from": str(item.get("fileDataFromDate") or "")[:10],
            "data_to": str(item.get("fileDataToDate") or "")[:10],
            "release_date": str(item.get("fileReleaseDate") or "")[:32],
            "over_advisory_cap": size > MAX_PREVIEW_BYTES,
        })
    return {
        "provider": "USPTO Open Data Portal",
        "product": product_id,
        "product_title": str(product.get("productTitleText") or PRODUCTS[product_id])[:140],
        "files": files,
        "files_previewed": len(files),
        "file_bytes_total": sum(x["bytes"] for x in files),
        "proposed_file_cap_bytes": MAX_PREVIEW_BYTES,
        "manual_only": True,
        "metadata_only": True,
        "no_files_downloaded": True,
        "no_data_stored": True,
        "does_not_include_patent_filtering": True,
        "notice": ("バルクZIPは分野を選別済みの文献ではありません。"
                   "ダウンロード前に公式提供条件・容量・分類フィルターを別途確認してください。"),
    }


def product_options():
    return {
        "products": [{"id": k, "description": v} for k, v in PRODUCTS.items()],
        "max_list": MAX_LIST, "max_window_days": 366,
        "download_implemented": True, "bounded_staging_only": True,
        "max_file_bytes": 512 * 1024 * 1024, "archive_parse_implemented": False,
        "manual_only": True,
        "upstream_project": "https://github.com/DunlapCoddingPC/pyUSPTO",
    }


def preview(api_key, *, product_id, limit=3, date_from=None, date_to=None):
    if type(product_id) is not str or product_id not in PRODUCTS:
        raise ValueError("USPTO公式の対応製品IDを選択してください")
    if type(limit) is not int or not 1 <= limit <= MAX_LIST:
        raise ValueError("一覧は最大10件までです")
    start, end = check_dates(date_from, date_to)
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("導入時にUSPTO ODPのAPIキーを登録してください")
    if len(api_key) > 512 or "\n" in api_key or "\r" in api_key:
        raise ValueError("USPTO APIキーが不正です")
    params = {"includeFiles": "true", "latest": "true" if start is None else "false",
              "limit": limit, "offset": 0}
    if start is not None:
        params.update({"fileDataFromDate": start, "fileDataToDate": end})
    endpoint = ODP_BASE + urllib.parse.quote(product_id, safe="")
    url = endpoint + "?" + urllib.parse.urlencode(params)
    raw = connectors.http_get(
        url, headers={"Accept": "application/json", "X-API-KEY": api_key},
        timeout=30, pace=2.0)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("USPTO製品の応答が2MiBを超えました")
    try:
        result = normalize_payload(raw, product_id, limit)
    except ValueError:
        raise connectors.ConnectorError("USPTO公式バルク製品の応答形式が不正です") from None
    result["date_filter"] = {"from": start, "to": end}
    return result
