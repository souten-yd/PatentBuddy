#!/usr/bin/env bash
# Build the QPKG with QNAP QDK (pinned commit). Used by .github/workflows/release.yml;
# runs locally too on any Linux with git, make, gcc and python3.
#   bash scripts/build-qpkg.sh <output-dir>
set -euo pipefail
QDK_COMMIT="${QDK_COMMIT:-78c77b898fecba8f860b630177248b5fa3f5baaf}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mkdir -p "${1:-dist}" && cd "${1:-dist}" && pwd)"
WORK="$(mktemp -d)"
[ -n "${KEEP_WORK:-}" ] || trap 'rm -rf "$WORK"' EXIT

[ -x /usr/bin/rsync ] || { echo "QDK qbuild needs /usr/bin/rsync (without it the data archive is silently empty)" >&2; exit 1; }
VERSION=$(sed -n 's/^QPKG_VER="\([^"]*\)"/\1/p' "$ROOT/qpkg/qpkg.cfg")
APPVER=$(python3 -c "import sys; sys.path.insert(0, '$ROOT'); import qnaplibrary; print(qnaplibrary.VERSION)")
[ "$VERSION" = "$APPVER" ] || { echo "version mismatch: qpkg.cfg=$VERSION app=$APPVER" >&2; exit 1; }

QDK="$WORK/QDK"
git clone --quiet --filter=blob:none https://github.com/qnap-dev/QDK.git "$QDK"
git -C "$QDK" checkout --quiet --detach "$QDK_COMMIT"
printf 'QDK_VERSION=2.5.3\nQDK_PATH="%s/shared"\n' "$QDK" > "$QDK/shared/qdk.conf"
make -s -C "$QDK/src"
export PATH="$QDK/src/bin:$PATH"

PKG="$WORK/pkg"
mkdir -p "$PKG/shared" "$PKG/icons"
cp "$ROOT/qpkg/qpkg.cfg" "$ROOT/qpkg/package_routines" "$PKG/"
cp "$ROOT/qpkg/shared/qnaplibrary.sh" "$ROOT/qpkg/shared/python3-path" "$PKG/shared/"
cp -R "$ROOT/qnaplibrary" "$PKG/shared/qnaplibrary"
find "$PKG/shared" -name '__pycache__' -prune -exec rm -rf {} +
cp "$ROOT/README.md" "$ROOT/CHANGELOG.md" "$PKG/shared/"
python3 "$ROOT/scripts/make-icons.py" "$PKG/icons" >/dev/null
chmod 755 "$PKG/shared/qnaplibrary.sh" "$PKG/shared/python3-path" "$QDK/shared/bin/qbuild"

(cd "$PKG" && QDK_PATH="$QDK/shared" "$QDK/shared/bin/qbuild" --root "$PKG" --build-dir "$PKG/build" --build-arch x86_64 --gzip)
pkg=$(find "$PKG/build" -maxdepth 2 -type f -name '*.qpkg' | head -n 1)
[ -n "$pkg" ] || { echo "QPKG was not produced" >&2; exit 1; }
name="QnapLibrary_${VERSION}_x86_64.qpkg"
python3 "$ROOT/scripts/inspect-qpkg.py" "$pkg"
cp "$pkg" "$OUT/$name"
(cd "$OUT" && sha256sum "$name" > "$name.sha256")
ls -l "$OUT/$name"
cat "$OUT/$name.sha256"
