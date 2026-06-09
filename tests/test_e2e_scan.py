"""End-to-end (offline, no Copilot, no network): scan the sample-spring-pcf fixture,
scaffold + validate the KB, and assert the headline P1 value is produced and provable.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.validation import validate_kb_tree

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp("work")
    return run_pipeline(str(FIXTURE), work_root=str(work), run_id="t", to_stage="validate")


def _load(root: Path) -> dict[tuple[str, str], dict]:
    docs = {}
    for p in (root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        docs[(d["kind"], d["metadata"]["name"])] = d
    return docs


def test_facts_and_artifacts_produced(result):
    assert result.facts > 5
    assert result.docs >= 8


def test_kb_validates_structurally_and_provenance(result):
    bad = [r for r in validate_kb_tree(result.root / "kb") if not r.ok]
    assert not bad, [(r.path, r.errors) for r in bad]


def test_flow_steps_ordered(result):
    flow = next(d for (k, _), d in _load(result.root).items() if k == "Flow")
    assert flow["status"] == "verified"
    names = [s["name"] for s in flow["spec"]["steps"]]
    assert any("reserve" in n for n in names)
    assert any("persist" in n for n in names)
    assert any("publish" in n for n in names)
    # the swallowed publish step must carry the data-loss failure mode
    pub = next(s for s in flow["spec"]["steps"] if "publish" in s["name"])
    assert any(fm.get("dataLossRisk") for fm in pub["failureModes"])


def test_alert_and_runbook_from_swallowed_failure(result):
    docs = _load(result.root)
    alert = docs[("Alert", "order-created-publish-failures")]
    assert alert["status"] == "needs-review"
    assert "splunk" in alert["spec"]["expr"]
    assert "order.created" in alert["spec"]["expr"]["splunk"]
    assert any(k == "Runbook" for (k, _) in docs)


def test_burn_rate_alert_from_slo_catalog(result):
    docs = _load(result.root)
    burn = docs[("Alert", "create-order-latency-burn-rate")]
    assert burn["status"] == "verified"
    assert burn["spec"]["alertType"] == "burn-rate"
    assert "prometheus_fast" in burn["spec"]["expr"]
    # Regression (latency-vs-availability bug): a latency SLO must burn on latency-bucket
    # violations (threshold 800ms -> le="0.8"), never on error rate.
    fast_expr = burn["spec"]["expr"]["prometheus_fast"]
    assert "http_server_requests_seconds_bucket" in fast_expr
    assert 'le="0.8"' in fast_expr
    assert 'outcome!="SUCCESS"' not in fast_expr
    # Route-scoped to the flow's own uri, not measured service-wide.
    uri = docs[("Flow", "create-order")]["spec"]["trigger"]["path"]
    assert f'uri="{uri}"' in fast_expr
    slo = docs[("SloSli", "create-order-latency")]
    assert slo["status"] == "verified"
    assert slo["spec"]["objectives"][0]["sli"] == "latency"
    assert slo["spec"]["objectives"][0]["target"] == 99.5
    assert slo["spec"]["objectives"][0]["errorBudgetPct"] == 0.5


def test_burn_rate_alert_renders_configured_backends(result):
    # render.alert_tools defaults to all four; the multi-backend adapter seam emits each, with the
    # new backends honestly represented (Wavefront percentile threshold; AppDynamics health rule).
    expr = _load(result.root)[("Alert", "create-order-latency-burn-rate")]["spec"]["expr"]
    assert "phi=" in expr["wavefront"]["query"]  # latency -> labelled percentile, not a fake ratio
    assert "NOT a multi-window budget burn-rate" in expr["wavefront"]["mechanism"]
    assert "<business-transaction>" in expr["appdynamics"]["healthRule"]["metricPath"]


def test_burn_rate_alert_carries_adopted_intent(result):
    # Tool-neutral AlertIntent spec adopted from resiliency-skills, on our envelope.
    spec = _load(result.root)[("Alert", "create-order-latency-burn-rate")]["spec"]
    assert spec["class"] == "symptom"
    assert spec["signal"]["type"] == "metric" and spec["signal"]["route"]
    br = spec["burnRate"]
    assert br["sli"] == "latency" and br["sloRef"] == "create-order-latency"
    # #M3: short/long windows (fast/slow rate) and factors are derived from BURN_WINDOWS, not
    # re-typed magic numbers — so the summary can't desync from the rendered PromQL.
    assert br["shortWindow"] == "1h" and br["longWindow"] == "6h"
    assert br["shortFactor"] == round(14.4 * br["budgetFraction"], 6)
    assert br["longFactor"] == round(6.0 * br["budgetFraction"], 6)
    # renderTargets honestly reflects only the backends that actually rendered (Splunk has no
    # burn-rate, so it's excluded).
    assert "prometheus" in spec["renderTargets"] and "splunk" not in spec["renderTargets"]


def test_blast_radius_flags_data_loss(result):
    brs = [d for (k, _), d in _load(result.root).items() if k == "BlastRadius"]
    assert any((d["spec"].get("stateful") or {}).get("dataLossRisk") for d in brs)


def test_readiness_includes_budget_finding(result):
    rs = next(d for (k, _), d in _load(result.root).items() if k == "ReadinessScore")
    gaps = " ".join(rs["spec"]["gaps"]).lower()
    assert "exceeds flow slo budget" in gaps


def test_provenance_tamper_is_caught(result):
    """Flip one cited line range and confirm provenance rejects it."""
    from sre_kb.validation.provenance import verify_evidence

    flow = next(d for (k, _), d in _load(result.root).items() if k == "Flow")
    tampered = {**flow, "evidence": [{**flow["evidence"][0], "lines": {"start": 1, "end": 1}}]}
    assert verify_evidence(tampered, FIXTURE.resolve())


def test_report_carries_stage_timings(result):
    """The engine's own observability: a slow run must say where the time went."""
    import json

    report = json.loads((result.root / "reports" / "validation_report.json").read_text())
    assert set(report["timingsMs"]) == {"scanMs", "scaffoldMs", "validateMs"}
    assert all(isinstance(v, int) and v >= 0 for v in report["timingsMs"].values())
