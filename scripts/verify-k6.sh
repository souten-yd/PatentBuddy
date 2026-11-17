#!/usr/bin/env bash
# K6 pre-merge integration gate. No changes to server runtime or GitHub Actions.
# Usage:
#   bash scripts/verify-k6.sh                 # full tests + Linux artifact
#   WITH_QPKG=1 bash scripts/verify-k6.sh     # plus QDK/QPKG build (network needed)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== K6: source, syntax, all unittest/HTTP/SQLite tests"
bash scripts/verify.sh

echo "== K6: ControlDeck embedded UI syntax"
if ! command -v node >/dev/null; then
  echo "ERROR: Node is required to verify the embedded workspace" >&2
  exit 1
fi
node --check qnaplibrary/web/addon-workspace.js

echo "== K6: validate current version triple (no version bump during Draft)"
python3 - <<'PY'
from pathlib import Path
import json
import re
from qnaplibrary import VERSION
qpkg = Path("qpkg/qpkg.cfg").read_text(encoding="utf-8")
match = re.search(r'^QPKG_VER="([^"]+)"$', qpkg, flags=re.M)
addon = json.loads(Path("addon.json").read_text(encoding="utf-8"))
if not match or VERSION != match.group(1) or VERSION != addon.get("version"):
    raise SystemExit("version mismatch between Python, QPKG and addon manifest")
print("version contract OK: " + VERSION)
PY

echo "== K6: package the Linux build (no startup npm build)"
bash scripts/build-linux.sh dist

if [ "${WITH_QPKG:-0}" = "1" ]; then
  echo "== K6: build QPKG with pinned QDK"
  bash scripts/build-qpkg.sh dist
  echo "QPKG: built; still requires QNAP installation + health verification"
else
  echo "QPKG: NOT TESTED (set WITH_QPKG=1 to build)"
fi
echo "K6 local gate finished; physical ControlDeck/Ubuntu/QNAP/iPhone E2E is separately required."
