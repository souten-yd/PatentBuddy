#!/usr/bin/env python3
"""Build an unsigned ControlDeck Feature bundle. Signing is separate.

Only explicitly allowlisted source files are packaged. No data_dir, logs,
credentials, symlinks, caches, or virtual environments enter the archive.
This artifact is NOT an installable trusted release until its canonical
manifest is signed with an approved publisher key.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def files_to_bundle(root: Path):
    files = [root / "addon.json", root / "control-deck-feature.json", root / "pb.sh"]
    files.extend(sorted(p for p in (root / "qnaplibrary").rglob("*")
                        if p.is_file() and p.suffix in {".py", ".html", ".js", ".css", ".svg", ".png"}))
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("bundle path escapes source root")
        if "__pycache__" in path.parts or "secrets" in path.name.lower():
            raise ValueError("invalid bundle source path")
    return files


def build(destination: Path, root: Path = ROOT) -> dict:
    addon = json.loads((root / "addon.json").read_text(encoding="utf-8"))
    package = json.loads((root / "control-deck-feature.json").read_text(encoding="utf-8"))
    namespace = {}
    exec((root / "qnaplibrary/__init__.py").read_text(encoding="utf-8"), namespace)
    version = namespace["VERSION"]
    if addon["version"] != version or package["version"] != version:
        raise ValueError("addon/package/Python versions disagree")
    if addon["id"] != package["feature_id"]:
        raise ValueError("feature and addon IDs disagree")
    if package["health_url"] != addon["runtime"]["base_url"] + addon["runtime"]["health_path"]:
        raise ValueError("feature and addon health endpoints disagree")
    output_name = f"control-deck-patent-buddy-{version}-linux-x86_64.tar.gz"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / output_name
    if path.is_symlink():
        raise ValueError("bundle output cannot be a symlink")
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as gz:
            with tarfile.open(mode="w", fileobj=gz, format=tarfile.PAX_FORMAT) as tar:
                for source in files_to_bundle(root):
                    payload = source.read_bytes()
                    info = tarfile.TarInfo(f"patent-buddy-{version}/{source.relative_to(root).as_posix()}")
                    info.size = len(payload)
                    info.mode = 0o755 if source.name == "pb.sh" else 0o644
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    tar.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"artifact": str(path), "version": version, "sha256": digest, "signed": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("dist"))
    options = parser.parse_args()
    print(json.dumps(build(options.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
