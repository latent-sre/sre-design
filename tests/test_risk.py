"""Computed blast-radius risk (#4): severity scales with breadth, criticality and
containment are separate axes, and the result is explainable. Plus the broad-impact
finding that the computed severity now drives."""

from __future__ import annotations

from sre_kb.reporting import collect_findings
from sre_kb.scoring.risk import assess


def test_uncontained_dependency_is_high_and_critical():
    r = assess(impacted_flows=1, data_loss=False, contained=False)
    assert r.severity == "high" and r.criticality == "critical"


def test_data_loss_is_high_and_critical():
    r = assess(impacted_flows=1, data_loss=True, contained=True)  # data loss overrides containment
    assert r.severity == "high" and r.criticality == "critical"


def test_contained_single_flow_is_medium_and_degraded():
    r = assess(impacted_flows=1, data_loss=False, contained=True)
    assert r.severity == "medium" and r.criticality == "degraded"


def test_severity_scales_with_breadth():
    # a bulkheaded dependency escalates medium -> high once many flows share it
    assert assess(impacted_flows=1, data_loss=False, contained=True).severity == "medium"
    assert assess(impacted_flows=3, data_loss=False, contained=True).severity == "high"


def test_rationale_is_explainable():
    r = assess(impacted_flows=2, data_loss=False, contained=False)
    assert "2 impacted flows" in r.rationale and "no bulkhead" in r.rationale


def test_broad_impact_finding_is_driven_by_computed_severity():
    doc = {
        "kind": "BlastRadius", "metadata": {"name": "shared-cache"}, "status": "verified",
        "spec": {
            "node": {"name": "shared-cache"}, "severityHint": "high",
            "impactedFlows": ["a", "b", "c"], "dependencyCriticality": "degraded",
            "containment": [{"kind": "ResiliencyPattern", "name": "cb"}],
        },
        "evidence": [{"path": "X.java", "lines": {"start": 1, "end": 1}}],
    }
    found = collect_findings([doc])
    assert found and found[0]["type"] == "broad-impact-dependency" and found[0]["severity"] == "high"
