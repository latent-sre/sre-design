#!/usr/bin/env bash
# Thin wrapper the sre-analyst agent calls: scan + scaffold a target repo, then print
# how to validate after enrichment. The engine never calls an LLM.
set -euo pipefail

TARGET="${1:?usage: run.sh <target-repo-path> [run-id]}"
RUN_ID="${2:-$(date +%Y%m%d-%H%M%S)}"

sre-kb run --target "$TARGET" --run "$RUN_ID" --to-stage scaffold
echo
echo "Scaffolded run '$RUN_ID' -> .work/$RUN_ID/candidates/"
echo "After enriching candidates, validate with:"
echo "  sre-kb run --target $TARGET --run $RUN_ID --to-stage validate"
