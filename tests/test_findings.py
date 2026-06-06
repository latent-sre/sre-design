"""Findings digest: ranked SRE risks aggregated from BlastRadius artifacts."""

from __future__ import annotations

from pathlib import Path

from sre_kb.pipeline import run as run_pipeline
from sre_kb.render import load_kb
from sre_kb.reporting import collect_findings, render_text

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def _docs(tmp_path):
    r = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="fnd", to_stage="validate")
    return load_kb(r.root)


def test_collect_ranks_data_loss_and_uncontained(tmp_path):
    found = collect_findings(_docs(tmp_path))
    types = [f["type"] for f in found]
    assert "data-loss-risk" in types  # order.created swallowed publish
    assert "uncontained-critical-dep" in types  # order-repository: critical db, no containment
    # contained dependency (inventory has a circuit breaker) is NOT a finding
    assert not any("inventory" in f["title"] for f in found)
    # all high-severity here, and data-loss ranks before uncontained
    assert found[0]["type"] == "data-loss-risk"
    assert all(f["severity"] == "high" for f in found)


def test_finding_carries_evidence_and_flow(tmp_path):
    dl = next(f for f in collect_findings(_docs(tmp_path)) if f["type"] == "data-loss-risk")
    assert "create-order" in dl["impactedFlows"]
    assert dl["evidence"] and ".java:" in dl["evidence"]
    assert dl["artifact"].startswith("BlastRadius/")


def test_render_text_digest(tmp_path):
    docs = _docs(tmp_path)
    text = render_text("order-service", "fnd", collect_findings(docs), docs)
    assert "[HIGH] data-loss-risk" in text
    assert "high" in text and "Artifacts:" in text


def test_no_findings_when_no_blast_radius():
    docs = [{"kind": "Flow", "metadata": {"name": "x"}, "status": "verified"}]
    found = collect_findings(docs)
    assert found == []
    assert "No high/medium-risk findings" in render_text("svc", "r", found, docs)
