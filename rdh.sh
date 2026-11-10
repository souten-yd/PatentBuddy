#!/bin/sh
# Preserve the caller's working directory so relative --data paths stay explicit.
set -eu
RDH_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# Put the chosen distribution first, even if cwd contains another checkout.
exec python3 -B -c 'import runpy, sys; sys.path.insert(0, sys.argv.pop(1)); runpy.run_module("researchdatahub.cli", run_name="__main__")' "$RDH_ROOT" "$@"
