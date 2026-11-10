#!/bin/sh
# PatentBuddy ControlDeck Add-on A0: no root / service installation / NAS migration.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PY=${PATENT_BUDDY_PYTHON:-python3}
CMD=${1:-doctor}
case "$CMD" in
  doctor)
    "$PY" - <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

print(json.dumps({
    "python": sys.version.split()[0],
    "sqlite": sqlite3.sqlite_version,
    "mode": "A0 only: no Host authentication, no migrated documents",
    "host_url": "http://127.0.0.1:9150/addon/v1/health",
}, ensure_ascii=False, indent=2))
PY
    ;;
  serve)
    [ "$(id -u)" -ne 0 ] || { echo "root cannot run PatentBuddy Add-on" >&2; exit 1; }
    DATA=${PATENT_BUDDY_DATA_DIR:-"$HOME/.local/share/patentbuddy"}
    case "$DATA" in
      /*) ;;
      *) echo "PATENT_BUDDY_DATA_DIR must be an absolute path" >&2; exit 2 ;;
    esac
    cd "$ROOT"
    export PYTHONPATH="$ROOT"
    exec "$PY" -B -m qnaplibrary --addon --data "$DATA" --bind 127.0.0.1 --port 9150
    ;;
  test)
    exec /bin/bash "$ROOT/scripts/verify.sh"
    ;;
  *)
    echo "Usage: ./pb.sh {doctor|serve|test}" >&2
    exit 2
    ;;
esac
