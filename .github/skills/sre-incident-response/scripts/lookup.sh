#!/usr/bin/env bash
# Consumer-side lookup: grep a PUBLISHED SRE KB tree for a symptom and list the artifacts
# that mention it. Read-only — this never runs the engine or touches the scanned service.
#   usage: lookup.sh <catalog-dir> <term>
# e.g.    lookup.sh catalog/orders inventory-service
#         lookup.sh catalog/orders "failed to publish"
set -euo pipefail

DIR="${1:?usage: lookup.sh <catalog-dir> <term>}"
TERM="${2:?usage: lookup.sh <catalog-dir> <term>}"

if [ ! -d "$DIR" ]; then
  echo "no such catalog dir: $DIR" >&2
  exit 2
fi

echo "# Artifacts in $DIR mentioning: $TERM"
echo
# -r recurse, -i case-insensitive, -l list files; restrict to KB yaml + rendered runbooks/findings.
matches=$(grep -rilF "$TERM" "$DIR/kb" "$DIR/runbooks" "$DIR/FINDINGS.md" 2>/dev/null | sort -u || true)

if [ -z "$matches" ]; then
  echo "(no direct match — check FINDINGS.md for known risks, then escalate)"
  exit 0
fi

echo "$matches" | while IFS= read -r f; do
  rel="${f#"$DIR"/}"
  echo "- $rel"
done
echo
echo "Open the Alert/Runbook/BlastRadius above; follow alertRef -> relatedFlow -> evidence path:line."
