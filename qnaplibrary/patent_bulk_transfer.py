"""Manually triggered USPTO ODP bulk ZIP staging: bounded, private, resumable.

Only a file selected from a fresh, authenticated official ODP product catalogue
may enter this component. Fixed origin and path, no redirects, archive extraction,
public file serving, automatic retries, scheduler, or ControlDeck execution.
Staging is intended for the Linux processing PC, not QNAP's busy RAID volume.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .patent_bulk_catalog import PRODUCTS, SAFE_FILE

MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_STAGING_BYTES = 2 * 1024 * 1024 * 1024
MIN_FREE_BYTES = 256 * 1024 * 1024
BUFFER_BYTES = 128 * 1024
MAX_TRANSFER_SECONDS = 900
ALLOWED_ETAG = re.compile(r'^"[\x21\x23-\x7e]{1,128}"$')
CONTENT_RANGE = re.compile(r"^bytes ([0-9]+)-([0-9]+)/([0-9]+)$")


class BulkTransferError(ValueError):
    """Safe, categorical message only; never propagate HTTP response bodies."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _filename(product, name):
    if type(product) is not str or product not in PRODUCTS:
        raise BulkTransferError("公式USPTO製品を選択してください")
    if (type(name) is not str or not SAFE_FILE.fullmatch(name) or
            name in (".", "..") or not name.lower().endswith(".zip")):
        raise BulkTransferError("ZIPのファイル名が不正です")
    return product, name


def _api_url(product, name):
    _filename(product, name)
    return ("https://api.uspto.gov/api/v1/datasets/products/files/" +
            urllib.parse.quote(product, safe="") + "/" +
            urllib.parse.quote(name, safe=""))


def _ensure_dir(base):
    """Create a server-owned directory, rejecting a symlink staging root."""
    base = Path(base)
    if base.is_symlink():
        raise BulkTransferError("保存先がシンボリックリンクです")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.is_symlink() or not base.is_dir():
        raise BulkTransferError("専用保存先を利用できません")
    return base


def _safe_file(path):
    if path.is_symlink():
        raise BulkTransferError("シンボリックリンクのファイルを使用できません")


def _write_json(path, data):
    _safe_file(path)
    temporary = path.with_name(path.name + ".new")
    _safe_file(temporary)
    if temporary.exists():
        temporary.unlink()  # clean orphaned metadata staging from a prior crash
    with open(temporary, "x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=True, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _read_json(path):
    _safe_file(path)
    try:
        if path.stat().st_size > 4096:
            raise BulkTransferError("保存済みメタデータが不正です")
        return json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise BulkTransferError("保存済みメタデータを確認できません") from None


def _hash_existing(path):
    digest = hashlib.sha256()
    with path.open("rb") as inp:
        while True:
            b = inp.read(BUFFER_BYTES)
            if not b:
                return digest.hexdigest()
            digest.update(b)


def _check_response(response, *, offset, expected):
    """Never append unless strong ETag + precise 206 byte range match."""
    status = response.getcode()
    headers = response.headers
    if headers.get("Content-Encoding", "identity").strip().lower() not in ("", "identity"):
        raise BulkTransferError("圧縮転送応答はファイルへ保存できません")
    declared = headers.get("Content-Length")
    needed = expected - offset
    if declared is None or not declared.isascii() or not declared.isdecimal() or int(declared) != needed:
        raise BulkTransferError("公式配布元のファイル長が一覧と一致しません")
    etag = (headers.get("ETag") or "").strip()
    if etag and not ALLOWED_ETAG.fullmatch(etag):
        raise BulkTransferError("再開用ETagが不正です")
    if offset == 0:
        if status != 200 or headers.get("Content-Range"):
            raise BulkTransferError("新規取得はHTTP 200のみ受け入れます")
    else:
        if status != 206:
            raise BulkTransferError("再開要求に対するHTTP 206がありません")
        match = CONTENT_RANGE.fullmatch((headers.get("Content-Range") or "").strip())
        if not match:
            raise BulkTransferError("Content-Rangeが不正です")
        begin, end, whole = map(int, match.groups())
        if (begin, end, whole) != (offset, expected - 1, expected):
            raise BulkTransferError("再開範囲とファイル全長が一致しません")
    return etag


class ManualBulkTransfer:
    def __init__(self, data_dir):
        self.root = Path(data_dir) / "bulk_staging"  # no user-selected arbitrary path
        self._guard = threading.Lock()
        self._cancel = threading.Event()
        self._current = None
        self._thread = None

    def _paths(self, product, name, *, create=False):
        product, name = _filename(product, name)
        root = _ensure_dir(self.root) if create else self.root
        if not create and (root.is_symlink() or not root.is_dir()):
            return None
        folder = _ensure_dir(root / product) if create else root / product
        if not create and (folder.is_symlink() or not folder.is_dir()):
            return None
        return (folder / (name + ".part"), folder / (name + ".meta.json"),
                folder / name, folder / (name + ".receipt.json"))

    def status(self, product=None, name=None):
        with self._guard:
            result = dict(self._current) if self._current else {
                "state": "idle", "manual_only": True, "no_auto_retry": True}
        if product is None and name is None:
            return result
        if not (isinstance(product, str) and isinstance(name, str)):
            raise BulkTransferError("製品とファイル名の両方を指定してください")
        _filename(product, name)
        if result.get("product") == product and result.get("file_name") == name:
            return result
        paths = self._paths(product, name, create=False)
        if not paths:
            return {"state": "not_downloaded", "manual_only": True}
        partial, meta_path, complete, receipt_path = paths
        for p in paths:
            _safe_file(p)
        if complete.is_file() and receipt_path.is_file():
            receipt = _read_json(receipt_path)
            return {"state": "completed", "product": product, "file_name": name,
                    "bytes_done": complete.stat().st_size,
                    "expected_bytes": receipt.get("expected_bytes"), "sha256": receipt.get("sha256"),
                    "manual_only": True, "file_not_publicly_served": True}
        if partial.is_file() and meta_path.is_file():
            meta = _read_json(meta_path)
            if meta.get("product") != product or meta.get("file_name") != name:
                raise BulkTransferError("途中ファイルの保存情報が一致しません")
            return {"state": "interrupted", "product": product, "file_name": name,
                    "bytes_done": partial.stat().st_size, "expected_bytes": meta.get("expected_bytes"),
                    "can_resume": bool(meta.get("etag")) and partial.stat().st_size > 0,
                    "manual_only": True}
        return {"state": "not_downloaded", "manual_only": True}

    def start(self, *, product, name, expected_bytes, key, source_lock, restart=False):
        _filename(product, name)
        if (type(expected_bytes) is not int or
                not 1 <= expected_bytes <= MAX_FILE_BYTES):
            raise BulkTransferError("1ファイルの保存上限512MiBを超えています")
        if type(restart) is not bool:
            raise BulkTransferError("再取得の指定が不正です")
        if type(key) is not str or not key or len(key) > 512 or "\r" in key or "\n" in key:
            raise BulkTransferError("導入後にUSPTOのAPIキーを設定してください")
        with self._guard:
            if self._thread and self._thread.is_alive():
                raise BulkTransferError("他のファイルを取得中です")
            self._cancel = threading.Event()
            state = {"state": "running", "product": product, "file_name": name,
                     "expected_bytes": expected_bytes, "bytes_done": 0,
                     "manual_only": True, "cancel_requested": False,
                     "file_not_publicly_served": True}
            self._current = state
            self._thread = threading.Thread(
                target=self._run, args=(product, name, expected_bytes, key, source_lock, restart),
                daemon=True, name="manual-odp-file")
            self._thread.start()
            return dict(state)

    def cancel(self, product, name):
        _filename(product, name)
        with self._guard:
            if not (self._thread and self._thread.is_alive() and self._current and
                    self._current["product"] == product and self._current["file_name"] == name):
                raise BulkTransferError("停止可能な取得がありません")
            self._cancel.set()
            self._current["cancel_requested"] = True
            return dict(self._current)

    def _update(self, **values):
        with self._guard:
            if self._current is not None:
                self._current.update(values)

    def _can_resume(self, product, name, expected):
        try:
            paths = self._paths(product, name)
            if not paths:
                return False
            part, meta_path = paths[:2]
            if not part.is_file() or not meta_path.is_file():
                return False
            meta = _read_json(meta_path)
            size = part.stat().st_size
            return (0 < size < expected and meta.get("expected_bytes") == expected and
                    bool(ALLOWED_ETAG.fullmatch(meta.get("etag", ""))))
        except (OSError, ValueError, TypeError):
            return False

    def _run(self, product, name, expected, key, source_lock, restart):
        try:
            self._download(product, name, expected, key, restart)
        except BulkTransferError as exc:
            self._update(state="cancelled" if self._cancel.is_set() else "failed",
                         reason=str(exc), can_resume=self._can_resume(product, name, expected))
        except (OSError, TimeoutError, urllib.error.URLError, ValueError):
            self._update(state="cancelled" if self._cancel.is_set() else "failed",
                         reason="ネットワークまたは保存先エラー",
                         can_resume=self._can_resume(product, name, expected))
        except Exception:
            # Never surface a credential-containing upstream exception.
            self._update(state="failed", reason="公式ファイルの取得に失敗しました",
                         can_resume=self._can_resume(product, name, expected))
        finally:
            source_lock.release()

    def _download(self, product, name, expected, key, restart):
        root = _ensure_dir(self.root)
        lock_path = root / ".manual-transfer.lock"
        _safe_file(lock_path)
        # flock blocks a second process from writing the same .part, but never
        # schedules a transfer or takes action without an admin start request.
        with lock_path.open("a+b") as process_lock:
            try:
                fcntl.flock(process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BulkTransferError("別プロセスがファイルを取得中です") from None
            try:
                return self._download_locked(product, name, expected, key, restart)
            finally:
                fcntl.flock(process_lock, fcntl.LOCK_UN)

    def _staging_used(self):
        total, scanned = 0, 0
        for folder in self.root.iterdir():
            if folder.name.startswith("."):
                continue
            if folder.is_symlink():
                raise BulkTransferError("保存先の構造に問題があります")
            if not folder.is_dir():
                continue
            for file in folder.iterdir():
                scanned += 1
                if scanned > 2000:
                    raise BulkTransferError("保存済みファイルが多いため容量を確認できません")
                _safe_file(file)
                if file.is_file() and (file.suffix == ".zip" or file.name.endswith(".zip.part")):
                    total += file.stat().st_size
        return total

    def _download_locked(self, product, name, expected, key, restart):
        paths = self._paths(product, name, create=True)
        part, meta_path, final, receipt_path = paths
        for p in paths:
            _safe_file(p)
        if restart:
            for p in paths:
                if p.exists():
                    p.unlink()  # explicit admin-confirmed restart only
        if final.exists():
            receipt = _read_json(receipt_path) if receipt_path.exists() else {}
            if (final.stat().st_size == expected and
                    receipt.get("expected_bytes") == expected and
                    receipt.get("sha256") == _hash_existing(final)):
                self._update(state="completed", bytes_done=expected,
                             sha256=receipt["sha256"], already_present=True)
                return
            raise BulkTransferError("既存ファイルのハッシュ照合ができません。再取得を明示してください")
        if shutil.disk_usage(part.parent).free < expected + MIN_FREE_BYTES:
            raise BulkTransferError("ディスク空き容量が不足しています")
        if part.exists() != meta_path.exists():
            raise BulkTransferError("途中保存の対応情報がありません。再取得を明示してください")
        offset, meta = 0, {}
        if part.exists():
            meta = _read_json(meta_path)
            offset = part.stat().st_size
            if (meta.get("product") != product or meta.get("file_name") != name or
                    meta.get("expected_bytes") != expected or
                    not 0 < offset < expected or not ALLOWED_ETAG.fullmatch(meta.get("etag", ""))):
                raise BulkTransferError("安全に再開できません。再取得を明示してください")
        used = self._staging_used()
        if used + expected - offset > MAX_STAGING_BYTES:
            raise BulkTransferError("専用領域の2GiB保存上限を超えています")
        self._update(bytes_done=offset)
        headers = {"X-API-KEY": key, "Accept": "application/octet-stream",
                   "Accept-Encoding": "identity", "User-Agent": "PatentBuddy-manual-bulk/0.1"}
        if offset:
            headers["Range"] = "bytes=%d-" % offset
            headers["If-Range"] = meta["etag"]
        request = urllib.request.Request(_api_url(product, name), headers=headers, method="GET")
        opener = urllib.request.build_opener(_NoRedirect())
        started = time.monotonic()
        try:
            response = opener.open(request, timeout=30)
        except urllib.error.HTTPError:
            raise BulkTransferError("公式配布元がHTTP取得要求を拒否しました（認証・制限・転送先を確認）") from None
        except urllib.error.URLError:
            raise BulkTransferError("公式配布元に接続できません") from None
        with response:
            etag = _check_response(response, offset=offset, expected=expected)
            if offset and etag != meta["etag"]:
                raise BulkTransferError("ETagが変わったため追記できません")
            if not offset:
                _write_json(meta_path, {"product": product, "file_name": name,
                                        "expected_bytes": expected, "etag": etag})
            digest = hashlib.sha256()
            if offset:
                with part.open("rb") as old:
                    while chunk := old.read(BUFFER_BYTES):
                        digest.update(chunk)
            flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if offset else os.O_EXCL)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(part, flags, 0o600)
            except FileExistsError:
                raise BulkTransferError("保存中のファイルが競合しています") from None
            with os.fdopen(descriptor, "ab" if offset else "wb") as stream:
                total = offset
                while total < expected:
                    if self._cancel.is_set():
                        raise BulkTransferError("利用者が取得を停止しました")
                    if time.monotonic() - started > MAX_TRANSFER_SECONDS:
                        raise BulkTransferError("最大転送時間を超えました")
                    chunk = response.read(min(BUFFER_BYTES, expected - total))
                    if not chunk:
                        raise BulkTransferError("途中で転送が切断されました")
                    if total == 0 and not chunk.startswith((b"PK\x03\x04", b"PK\x05\x06",
                                                             b"PK\x07\x08")):
                        raise BulkTransferError("ZIP以外の応答はファイルに保存できません")
                    stream.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                    self._update(bytes_done=total)
                if response.read(1):
                    raise BulkTransferError("配布ファイルが事前サイズを超えました")
                stream.flush()
                os.fsync(stream.fileno())
        if self._cancel.is_set():
            raise BulkTransferError("利用者が取得を停止しました")
        checksum = digest.hexdigest()
        os.replace(part, final)
        _write_json(receipt_path, {"product": product, "file_name": name,
                                   "expected_bytes": expected, "sha256": checksum})
        if meta_path.exists():
            meta_path.unlink()
        self._update(state="completed", bytes_done=expected, sha256=checksum,
                     can_resume=False, already_present=False)
