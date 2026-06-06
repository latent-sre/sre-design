"""Multiplicity (#3): multiple endpoints -> multiple Flows, and a shared dependency's
BlastRadius aggregates impactedFlows across them (was fs.first => one flow only)."""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.pipeline import run as run_pipeline

MULTIFLOW = Path(__file__).parent / "fixtures" / "sample-multiflow"


def _kb(tmp_path):
    r = run_pipeline(str(MULTIFLOW), work_root=str(tmp_path), run_id="mf", to_stage="validate")
    return {(d["kind"], d["metadata"]["name"]): d
            for p in (r.root / "kb").rglob("*.yaml") for d in [yaml.safe_load(p.read_text())]}


def test_each_endpoint_becomes_its_own_flow(tmp_path):
    docs = _kb(tmp_path)
    flows = {name for (kind, name) in docs if kind == "Flow"}
    assert flows == {"open-account", "close-account"}
    for fname in flows:
        kinds = [s["kind"] for s in docs[("Flow", fname)]["spec"]["steps"]]
        assert "db-write" in kinds  # each handler body has its own persist step


def test_shared_dependency_aggregates_impacted_flows(tmp_path):
    docs = _kb(tmp_path)
    br = docs[("BlastRadius", "account-repository")]
    assert set(br["spec"]["impactedFlows"]) == {"open-account", "close-account"}  # not just the first
