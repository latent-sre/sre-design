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
    risks = [f for f in found if f["severity"] != "info"]
    assert all(f["severity"] == "high" for f in risks)
    # the PCF fixture has no cf-env snapshot, so the §4.3 adoption nudge rides along (info, last)
    assert found[-1]["type"] == "missing-cf-env-snapshot"


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


def test_critical_severity_outranks_high_and_is_counted():
    # A co-tenancy datastore emits severityHint "critical"; it must sort above "high" and be
    # counted in the tally, not fall to the bottom of the digest (was rank 9, uncounted).
    docs = [
        {"kind": "BlastRadius", "metadata": {"name": "dep"}, "status": "verified",
         "spec": {"node": {"name": "dep"}, "severityHint": "high",
                  "dependencyCriticality": "critical", "impactedFlows": ["b"]},
         "evidence": [{"path": "Y.java", "lines": {"start": 1, "end": 1}}]},
        {"kind": "BlastRadius", "metadata": {"name": "shared-db"}, "status": "verified",
         "spec": {"node": {"name": "shared-db"}, "severityHint": "critical",
                  "stateful": {"dataLossRisk": True}, "impactedFlows": ["a"]},
         "evidence": [{"path": "X.java", "lines": {"start": 1, "end": 1}}]},
    ]
    found = collect_findings(docs)
    assert found[0]["severity"] == "critical"  # sorts above the "high" finding
    assert "2 high" in render_text("svc", "r", found, docs)  # critical counted as high-or-above


# --- §4.3 snapshot adoption nudges -----------------------------------------------------------
_PCF_DEP = {"kind": "Deployment", "metadata": {"name": "orders"},
            "spec": {"hosting": "PCF"}, "evidence": [{"path": "manifest.yml",
                                                      "lines": {"start": 1, "end": 5}}]}


def test_pcf_app_without_snapshot_gets_an_adoption_nudge():
    found = collect_findings([_PCF_DEP])
    nudge = [f for f in found if f["type"] == "missing-cf-env-snapshot"]
    assert len(nudge) == 1 and nudge[0]["severity"] == "info"
    assert ".sre/cf-env.json" in nudge[0]["detail"]


def test_fresh_snapshot_yields_no_nudge():
    from datetime import UTC, datetime

    docs = [_PCF_DEP,
            {"kind": "Topology", "metadata": {"name": "orders"},
             "spec": {"pcfSpaces": [{"organization": "acme", "space": "prod"}]}},
            {"kind": "Dependency", "metadata": {"name": "db"},
             "spec": {"name": "db", "type": "datastore",
                      "snapshot": {"capturedAt": datetime.now(UTC).isoformat()}}}]
    assert [f for f in collect_findings(docs) if "cf-env" in f["type"]] == []


def test_stale_snapshot_gets_a_refresh_nudge():
    docs = [_PCF_DEP,
            {"kind": "Topology", "metadata": {"name": "orders"},
             "spec": {"pcfSpaces": [{"organization": "acme", "space": "prod"}]}},
            {"kind": "Dependency", "metadata": {"name": "db"},
             "spec": {"name": "db", "type": "datastore",
                      "snapshot": {"capturedAt": "2020-01-01T00:00:00Z"}}}]
    stale = [f for f in collect_findings(docs) if f["type"] == "stale-cf-env-snapshot"]
    assert len(stale) == 1 and stale[0]["severity"] == "info"
    assert "day(s) old" in stale[0]["title"]


def test_non_pcf_kb_gets_no_snapshot_findings():
    assert [f for f in collect_findings([{"kind": "TechStack", "metadata": {"name": "x"},
                                          "spec": {}}])
            if "cf-env" in f["type"]] == []
