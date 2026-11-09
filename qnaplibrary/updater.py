"""Self-update from GitHub Releases with SHA-256 verification.

Install modes (env QNAPLIBRARY_INSTALL_MODE, set by the launchers):
* linux : INSTALL_ROOT/versions/<ver>/ + INSTALL_ROOT/current symlink. Apply = extract the verified
          tar.gz into versions/<new>, switch the symlink atomically, then exit with code 75 so the
          service manager (systemd Restart=always / the runner loop) starts the new version.
          The previous version stays in versions/ for rollback (`install.sh rollback`).
* qpkg  : the verified .qpkg is run with /bin/sh in a detached session; the QTS installer stops,
          replaces and restarts the app. Data lives outside the QPKG directory and is preserved.
* dev   : check only.
Asset names are fixed: QnapLibrary_<v>_x86_64.qpkg and qnaplibrary-<v>-linux.tar.gz.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import REPO, VERSION

LOG = logging.getLogger("qnaplibrary.updater")
VERSION_RE = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
MAX_ASSET = 256 * 1024 * 1024
API = "https://api.github.com/repos/%s/releases/latest" % REPO
RESTART_EXIT_CODE = 75


def parse_version(value):
    m = VERSION_RE.match(value or "")
    if not m:
        raise ValueError("version must be X.Y.Z")
    return tuple(int(x) for x in m.groups())


def install_mode():
    return os.environ.get("QNAPLIBRARY_INSTALL_MODE", "dev")


def asset_name(version, mode):
    if mode == "qpkg":
        return "QnapLibrary_%s_x86_64.qpkg" % version
    return "qnaplibrary-%s-linux.tar.gz" % version


def select(release, current, mode):
    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease"):
        return None
    try:
        new = parse_version(tag)
    except ValueError:
        return None
    if new <= parse_version(current):
        return None
    version = ".".join(map(str, new))
    name = asset_name(version, "qpkg" if mode == "qpkg" else "linux")
    assets = [a for a in release.get("assets", []) if a.get("name") == name]
    if len(assets) != 1:
        raise ValueError("リリース %s に %s がありません" % (tag, name))
    a = assets[0]
    digest = a.get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ValueError("リリース資産に SHA-256 digest がありません")
    url = "https://github.com/%s/releases/download/%s/%s" % (REPO, tag, name)
    if a.get("browser_download_url", "").lower() != url.lower():
        raise ValueError("想定外のダウンロードURLです")
    size = a.get("size")
    if not isinstance(size, int) or not 0 < size <= MAX_ASSET:
        raise ValueError("資産サイズが不正です")
    return {"version": version, "tag": tag, "name": name, "url": a["browser_download_url"],
            "sha256": digest[7:].lower(), "size": size, "notes": (release.get("body") or "")[:4000],
            "published_at": release.get("published_at")}


def fetch_latest(timeout=15):
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "QnapLibrary-updater/%s" % VERSION})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(4 * 1024 * 1024))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def download(asset, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / asset["name"]
    tmp = directory / (asset["name"] + ".part")
    req = urllib.request.Request(asset["url"], headers={"User-Agent": "QnapLibrary-updater/%s" % VERSION})
    digest, count = hashlib.sha256(), 0
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        while True:
            block = resp.read(1 << 20)
            if not block:
                break
            count += len(block)
            if count > asset["size"] or count > MAX_ASSET:
                raise ValueError("ダウンロードサイズが一致しません")
            digest.update(block)
            out.write(block)
    if count != asset["size"] or digest.hexdigest() != asset["sha256"]:
        tmp.unlink()
        raise ValueError("SHA-256 が一致しません（改ざんまたは破損）")
    os.replace(str(tmp), str(target))
    return target


def safe_extract(tar_path, dest):
    dest = Path(dest).resolve()
    with tarfile.open(tar_path, "r:gz") as tar:
        for m in tar.getmembers():
            p = (dest / m.name).resolve()
            if not str(p).startswith(str(dest) + os.sep) and p != dest:
                raise ValueError("不正なパスを含むアーカイブです: %s" % m.name)
            if m.issym() or m.islnk() or m.isdev():
                raise ValueError("リンク/デバイスを含むアーカイブは拒否します: %s" % m.name)
        tar.extractall(str(dest))


class Updater:
    def __init__(self, config, data_dir, shutdown=None):
        self.config = config
        self.dir = Path(data_dir) / "updates"
        self.mode = install_mode()
        self.root = Path(os.environ.get("QNAPLIBRARY_INSTALL_ROOT", "")) if os.environ.get("QNAPLIBRARY_INSTALL_ROOT") else None
        self.shutdown = shutdown
        self.state = {"current": VERSION, "mode": self.mode, "latest": None, "checked_at": None,
                      "phase": "idle", "message": "", "error": None}
        self._lock = threading.Lock()
        self._timer = None

    def status(self):
        with self._lock:
            return dict(self.state)

    def _set(self, **kw):
        with self._lock:
            self.state.update(kw)

    def check(self):
        try:
            release = fetch_latest()
            asset = select(release, VERSION, self.mode) if release else None
            self._set(latest=asset, checked_at=time.time(), error=None,
                      message="最新です" if not asset else "v%s が利用できます" % asset["version"])
            return asset
        except Exception as error:
            self._set(checked_at=time.time(), error=str(error)[:300], message="更新確認に失敗しました")
            LOG.warning("update check failed: %s", error)
            return None

    def apply(self):
        if self.mode not in ("linux", "qpkg"):
            raise ValueError("開発モードでは自動更新できません（パッケージ版で利用してください）")
        with self._lock:
            if self.state["phase"] in ("downloading", "installing"):
                raise ValueError("更新処理が進行中です")
            self.state["phase"] = "downloading"
        asset = self.check()
        if not asset:
            self._set(phase="idle")
            raise ValueError("新しいリリースはありません")
        threading.Thread(target=self._apply, args=(asset,), daemon=True).start()
        return asset

    def _apply(self, asset):
        try:
            self._set(phase="downloading", message="ダウンロード中 v%s" % asset["version"])
            path = download(asset, self.dir)
            self._set(phase="installing", message="インストール中")
            if self.mode == "qpkg":
                self._apply_qpkg(path)
            else:
                self._apply_linux(path, asset["version"])
        except Exception as error:
            LOG.exception("update failed")
            self._set(phase="failed", error=str(error)[:300], message="更新に失敗しました")

    def _apply_qpkg(self, path):
        log = open(str(self.dir / "install.log"), "ab")
        subprocess.Popen(["/bin/sh", str(path)], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         cwd=str(self.dir), start_new_session=True, close_fds=True)
        self._set(message="QPKG インストーラを起動しました。まもなく再起動します")

    def _apply_linux(self, path, version):
        if not self.root or not (self.root / "versions").is_dir():
            raise ValueError("インストール先 (QNAPLIBRARY_INSTALL_ROOT) が不明です")
        target = self.root / "versions" / version
        staging = self.root / "versions" / (".staging-" + version)
        shutil.rmtree(str(staging), ignore_errors=True)
        staging.mkdir(parents=True)
        safe_extract(path, staging)
        inner = staging / ("qnaplibrary-%s" % version)
        src = inner if inner.is_dir() else staging
        if not (src / "qnaplibrary" / "__init__.py").is_file():
            raise ValueError("アーカイブにアプリ本体がありません")
        check = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import qnaplibrary.server",
                                str(src)], stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        if check.returncode != 0:
            raise ValueError("新バージョンの起動前チェックに失敗: %s" % check.stderr.decode()[-300:])
        shutil.rmtree(str(target), ignore_errors=True)
        os.replace(str(src), str(target))
        shutil.rmtree(str(staging), ignore_errors=True)
        link = self.root / "current"
        tmp_link = self.root / ".current.new"
        if tmp_link.is_symlink() or tmp_link.exists():
            tmp_link.unlink()
        os.symlink(os.path.join("versions", version), str(tmp_link))
        os.replace(str(tmp_link), str(link))
        self._prune()
        self._set(phase="restarting", message="v%s に切り替えました。再起動します" % version)
        if self.shutdown:
            threading.Timer(1.0, self.shutdown, args=(RESTART_EXIT_CODE,)).start()

    def _prune(self, keep=3):
        versions = []
        for p in (self.root / "versions").iterdir():
            try:
                versions.append((parse_version(p.name), p))
            except ValueError:
                continue
        current = os.path.realpath(str(self.root / "current"))
        for _, p in sorted(versions)[:-keep]:
            if os.path.realpath(str(p)) != current:
                shutil.rmtree(str(p), ignore_errors=True)

    # periodic check (RAM timer, daily) ---------------------------------------
    def start_background(self):
        if not self.config.get("update", "auto_check", default=True):
            return

        def tick():
            asset = self.check()
            if asset and self.config.get("update", "auto_apply", default=False) and self.mode in ("linux", "qpkg"):
                try:
                    self.apply()
                except ValueError as error:
                    LOG.info("auto update skipped: %s", error)
            self._timer = threading.Timer(24 * 3600, tick)
            self._timer.daemon = True
            self._timer.start()
        self._timer = threading.Timer(90, tick)
        self._timer.daemon = True
        self._timer.start()
