#!/usr/bin/env bash
# Local verification (run before every merge; there is no PR CI by design).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "== python syntax"
python3 -m py_compile qnaplibrary/*.py scripts/*.py
echo "== js syntax"
if command -v node >/dev/null; then node --check qnaplibrary/web/app.js; else echo "node not found: skipped"; fi
echo "== shell syntax"
for f in qpkg/shared/qnaplibrary.sh qpkg/shared/python3-path packaging/linux/install.sh scripts/*.sh; do sh -n "$f"; done
echo "== stdlib-only imports"
python3 - <<'EOF'
import ast, pathlib, sys
allowed_optional = {"numpy"}
std = set(sys.stdlib_module_names)
bad = []
for p in pathlib.Path("qnaplibrary").glob("*.py"):
    for node in ast.walk(ast.parse(p.read_text())):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else []
        for n in names:
            top = n.split(".")[0]
            if top not in std and top != "qnaplibrary" and top not in allowed_optional:
                bad.append(f"{p}: {n}")
if bad:
    sys.exit("non-stdlib imports:\n" + "\n".join(bad))
print("ok")
EOF
echo "== no secrets / shell=True"
! grep -rn "shell=True" qnaplibrary/ || { echo "shell=True found" >&2; exit 1; }
echo "== unit + api tests"
python3 -m unittest discover -s tests -t . -q
echo "verify: OK"
