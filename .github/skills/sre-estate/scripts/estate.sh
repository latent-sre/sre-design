#!/usr/bin/env bash
# Thin wrapper for an estate scan across >=2 service repos. The engine never calls an LLM;
# this just runs the deterministic cross-service topology + co-tenancy blast radius.
#   usage: estate.sh <repo1> <repo2> [repo3 ...]
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: estate.sh <repo1> <repo2> [repo3 ...]   (>=2 targets for cross-service work)" >&2
  exit 2
fi

args=()
for repo in "$@"; do
  args+=(--target "$repo")
done

sre-kb estate "${args[@]}"
echo
echo "Estate scan complete. Inspect:"
echo "  .work/<estate-run>/kb/**/Topology/      cross-service graph"
echo "  .work/<estate-run>/kb/**/BlastRadius/   co-tenancy + impacted services"
echo "  .work/<estate-run>/projections/diagrams/topology.mmd"
