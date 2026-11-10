#!/bin/sh
# Preserve the caller's working directory so relative --data paths stay explicit.
set -eu
RDH_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="$RDH_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -B -m researchdatahub.cli "$@"
