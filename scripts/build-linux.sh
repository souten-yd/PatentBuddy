#!/usr/bin/env bash
# Build the Linux server package: qnaplibrary-<ver>-linux.tar.gz (+ .sha256)
#   bash scripts/build-linux.sh <output-dir>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mkdir -p "${1:-dist}" && cd "${1:-dist}" && pwd)"
VERSION=$(python3 -c "import sys; sys.path.insert(0, '$ROOT'); import qnaplibrary; print(qnaplibrary.VERSION)")
CFG=$(sed -n 's/^QPKG_VER="\([^"]*\)"/\1/p' "$ROOT/qpkg/qpkg.cfg")
[ "$VERSION" = "$CFG" ] || { echo "version mismatch: app=$VERSION qpkg.cfg=$CFG" >&2; exit 1; }
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
DIR="$WORK/qnaplibrary-$VERSION"
mkdir -p "$DIR"
cp -R "$ROOT/qnaplibrary" "$DIR/qnaplibrary"
find "$DIR" -name '__pycache__' -prune -exec rm -rf {} +
cp "$ROOT/packaging/linux/install.sh" "$ROOT/packaging/linux/qnaplibrary.service.in" "$ROOT/README.md" "$ROOT/CHANGELOG.md" "$DIR/"
cp "$ROOT/scripts/client/qnaplibrary_client.py" "$DIR/"
cp "$ROOT/scripts/client/qnaplibrary_client.py" "$OUT/qnaplibrary_client.py"
chmod 755 "$DIR/install.sh" "$DIR/qnaplibrary_client.py"
echo "$VERSION" > "$DIR/VERSION"
name="qnaplibrary-$VERSION-linux.tar.gz"
# reproducible-ish archive: fixed owner, sorted names, mtime from the last commit if available
MTIME=$(git -C "$ROOT" log -1 --format=%cI 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="$MTIME" -C "$WORK" -czf "$OUT/$name" "qnaplibrary-$VERSION"
(cd "$OUT" && sha256sum "$name" > "$name.sha256")
ls -l "$OUT/$name"
cat "$OUT/$name.sha256"
