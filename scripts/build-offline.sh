#!/usr/bin/env bash
# Build an offline wheelhouse for air-gapped / PCF installs (HYBRID-PLAN §9.7 R8 / DEEP-COMPARISON R9).
#
# Produces the sre-kb engine wheel plus every runtime dependency wheel, so a disconnected runner
# can install with no package index:
#
#   pip install --no-index --find-links dist/wheels sre-kb
#
# Schemas and the default config ship inside the wheel as package data, so the offline install is
# fully self-contained — no repo checkout is needed at runtime. Run this on a connected host; copy
# the resulting directory to the air-gapped target.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="${1:-dist/wheels}"
rm -rf "$OUT"
mkdir -p "$OUT"
python -m pip wheel . --wheel-dir "$OUT"
count=$(find "$OUT" -name '*.whl' | wc -l | tr -d ' ')
echo
echo "Offline wheelhouse: ${count} wheels in ${OUT}/"
echo "Install offline:  pip install --no-index --find-links ${OUT} sre-kb"
