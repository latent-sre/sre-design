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
    slo = docs[("SloSli", "create-order-latency")]
    assert slo["status"] == "verified"
    assert slo["spec"]["objectives"][0]["target"] == 99.5
    assert slo["spec"]["objectives"][0]["errorBudgetPct"] == 0.5


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
