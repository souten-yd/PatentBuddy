#!/bin/sh
# QnapLibrary Linux installer.
#   ./install.sh                 # per-user install (~/.local/share/qnaplibrary) + systemd --user service
#   sudo ./install.sh --system   # /opt/qnaplibrary, data /var/lib/qnaplibrary, runs as user "qnaplibrary"
#   ./install.sh rollback        # switch back to the previous installed version
#   ./install.sh uninstall       # remove program files (data is kept)
# Options: --prefix DIR --data DIR --port N --no-service
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERSION=$(cat "$HERE/VERSION")
MODE=user; ACTION=install; SERVICE=1; PORT=""
PREFIX=""; DATA=""
while [ $# -gt 0 ]; do
    case "$1" in
        --system) MODE=system ;;
        --prefix) PREFIX="$2"; shift ;;
        --data) DATA="$2"; shift ;;
        --port) PORT="$2"; shift ;;
        --no-service) SERVICE=0 ;;
        install|rollback|uninstall) ACTION="$1" ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
if [ "$MODE" = system ]; then
    [ "$(id -u)" = 0 ] || { echo "--system requires root (sudo)" >&2; exit 1; }
    PREFIX=${PREFIX:-/opt/qnaplibrary}; DATA=${DATA:-/var/lib/qnaplibrary}
    UNIT_DIR=/etc/systemd/system; SCTL="systemctl"; RUN_USER=qnaplibrary
else
    [ "$(id -u)" != 0 ] || { echo "per-user install as root is refused; use --system" >&2; exit 1; }
    PREFIX=${PREFIX:-$HOME/.local/share/qnaplibrary}; DATA=${DATA:-$HOME/.local/share/qnaplibrary-data}
    UNIT_DIR=$HOME/.config/systemd/user; SCTL="systemctl --user"; RUN_USER=""
fi
PY=$(command -v python3 || true)
[ -n "$PY" ] && "$PY" -c 'import sys, sqlite3; sys.exit(sys.version_info < (3, 9))' || { echo "Python 3.9+ (with sqlite3) is required" >&2; exit 1; }
have_systemd() { command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; }

case "$ACTION" in
rollback)
    cur=$(readlink "$PREFIX/current" | sed 's#.*/##')
    prev=$(ls "$PREFIX/versions" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -t. -k1,1n -k2,2n -k3,3n | grep -B1 -x "$cur" | head -n1)
    [ -n "$prev" ] && [ "$prev" != "$cur" ] || { echo "no previous version to roll back to" >&2; exit 1; }
    ln -sfn "versions/$prev" "$PREFIX/current"
    echo "rolled back $cur -> $prev"
    have_systemd && $SCTL restart qnaplibrary 2>/dev/null || true
    exit 0 ;;
uninstall)
    have_systemd && { $SCTL disable --now qnaplibrary 2>/dev/null || true; rm -f "$UNIT_DIR/qnaplibrary.service"; $SCTL daemon-reload || true; }
    rm -rf "$PREFIX"
    echo "removed $PREFIX (data kept in $DATA)"
    exit 0 ;;
esac

mkdir -p "$PREFIX/versions" "$PREFIX/bin" "$DATA"
rm -rf "$PREFIX/versions/$VERSION"
mkdir -p "$PREFIX/versions/$VERSION"
cp -R "$HERE/qnaplibrary" "$HERE/VERSION" "$HERE/README.md" "$HERE/CHANGELOG.md" "$PREFIX/versions/$VERSION/"
cp -R "$HERE/researchdatahub" "$HERE/rdh.sh" "$PREFIX/versions/$VERSION/"
ln -sfn "versions/$VERSION" "$PREFIX/current"
cp "$HERE/install.sh" "$PREFIX/install.sh"; cp "$HERE/VERSION" "$PREFIX/VERSION"; cp -R "$HERE/qnaplibrary.service.in" "$PREFIX/"
cat > "$PREFIX/bin/qnaplibrary" <<EOF
#!/bin/sh
export QNAPLIBRARY_INSTALL_MODE=linux QNAPLIBRARY_INSTALL_ROOT="$PREFIX" PYTHONPATH="$PREFIX/current"
${PORT:+export QNAPLIBRARY_PORT=$PORT}
# python -m puts the working directory first on sys.path: run from the install root so a
# qnaplibrary/ folder in the caller's directory can never shadow the installed version.
cd "$PREFIX" || exit 1
exec "$PY" -B -m qnaplibrary "\$@"
EOF
cat > "$PREFIX/bin/qnaplibrary-run" <<EOF
#!/bin/sh
# Foreground runner for systems without systemd: restarts after self-update (exit 75).
while :; do "$PREFIX/bin/qnaplibrary" --data "$DATA" "\$@"; c=\$?; [ "\$c" -eq 75 ] || exit "\$c"; sleep 1; done
EOF
chmod 755 "$PREFIX/bin/qnaplibrary" "$PREFIX/bin/qnaplibrary-run"

if [ "$MODE" = system ]; then
    id "$RUN_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$RUN_USER"
    chown -R "$RUN_USER:" "$DATA" "$PREFIX"
    HARDEN="User=$RUN_USER
ProtectSystem=strict
ReadWritePaths=$DATA $PREFIX
ProtectHome=yes"
    WANTED=multi-user.target
else
    HARDEN=""; WANTED=default.target
fi
chmod 700 "$DATA"

if [ "$SERVICE" = 1 ] && have_systemd; then
    mkdir -p "$UNIT_DIR"
    sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@DATA@#$DATA#g" -e "s#@WANTED@#$WANTED#g" "$HERE/qnaplibrary.service.in" |
        awk -v h="$HARDEN" '{ if ($0 == "@HARDEN@") print h; else print }' > "$UNIT_DIR/qnaplibrary.service"
    $SCTL daemon-reload
    $SCTL enable qnaplibrary >/dev/null 2>&1 || true
    $SCTL restart qnaplibrary
    [ "$MODE" = user ] && command -v loginctl >/dev/null 2>&1 && loginctl enable-linger "$(id -un)" 2>/dev/null || true
    echo "QnapLibrary $VERSION installed and started ($SCTL status qnaplibrary)"
else
    echo "QnapLibrary $VERSION installed. Start with: $PREFIX/bin/qnaplibrary-run"
fi
echo "Web UI: http://<this-host>:${PORT:-17871}/   data: $DATA"
