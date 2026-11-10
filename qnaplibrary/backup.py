"""On-demand SQLite snapshots; no automatic disk writes or arbitrary paths."""
import os
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


class BackupError(ValueError):
    pass


class Backups:
    """Back up the authoritative SQLite DB; settings/secrets remain separate."""

    def __init__(self, store):
        self.store = store
        self.directory = Path(store.path).parent / "backups"
        self.lock = threading.Lock()

    def _directory(self, create=False):
        if self.directory.is_symlink():
            raise BackupError("バックアップ先にシンボリックリンクは使用できません")
        if create:
            self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
            os.chmod(self.directory, 0o700)
        if not self.directory.exists():
            return None
        if not self.directory.is_dir():
            raise BackupError("バックアップ先がディレクトリではありません")
        return self.directory

    @staticmethod
    def _item(path):
        st = path.stat()
        return {"name": path.name, "path": "backups/" + path.name,
                "bytes": st.st_size, "created": st.st_mtime}

    def list(self):
        directory = self._directory()
        if directory is None:
            return []
        files = sorted(directory.glob("qnaplibrary-*.sqlite3"), reverse=True)
        return [self._item(f) for f in files[:100] if not f.is_symlink() and f.is_file()]

    def create(self):
        # Serialize concurrent requests and writes on the shared SQLite connection.
        with self.lock:
            try:
                directory = self._directory(create=True)
            except OSError as exc:
                raise BackupError("バックアップ先を作成できません: " + str(exc)) from exc
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            name = "qnaplibrary-" + stamp + ".sqlite3"
            target = directory / name
            partial = directory / ("." + name + ".partial")
            if os.path.lexists(target) or os.path.lexists(partial):
                raise BackupError("バックアップ名が重複しました。再試行してください")
            try:
                with self.store.lock:
                    page_count = self.store.db.execute("PRAGMA page_count").fetchone()[0]
                    page_size = self.store.db.execute("PRAGMA page_size").fetchone()[0]
                    if shutil.disk_usage(directory).free < page_count * page_size + 64 * 1024 * 1024:
                        raise BackupError("ディスク空き容量が不足しています")
                    self.store.db.execute("VACUUM INTO ?", (str(partial),))
                uri = "file:" + quote(str(partial), safe="/") + "?mode=ro"
                with sqlite3.connect(uri, uri=True) as snapshot:
                    result = snapshot.execute("PRAGMA quick_check").fetchone()[0]
                    if result != "ok":
                        raise BackupError("バックアップの整合性確認に失敗しました")
                os.chmod(partial, 0o600)
                os.replace(partial, target)
                return self._item(target)
            except (sqlite3.Error, OSError, BackupError) as exc:
                if partial.exists() or partial.is_symlink():
                    partial.unlink()
                if isinstance(exc, BackupError):
                    raise
                raise BackupError("バックアップ作成に失敗しました: " + str(exc)) from exc
