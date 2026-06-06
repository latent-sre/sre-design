"""The Copilot challenge loop: engine emits a worklist of judgment-call claims, an oracle
adjudicates them, and `challenge-apply` re-gates deterministically (downgrade-only)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.pipeline.challenge_apply import apply_verdicts
from sre_kb.validation.challenge import extract_review_claims
from sre_kb.workspace import RunLayout

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
RUNBOOK = "Runbook/order-created-publish-failures"
ALERT = "Alert/order-created-publish-failures"


def _run(tmp):
    return run_pipeline(str(FIXTURE), work_root=str(tmp), run_id="cl", to_stage="validate")


def _layout(tmp):
    return RunLayout(Path(str(tmp)), "cl")


def _status(layout, kind, name):
    for sub, st in (("kb/verified", "verified"), ("kb/needs-review", "needs-review"), ("reports/rejected", "rejected")):
        if (layout.root / sub / kind / f"{name}.yaml").exists():
            return st
    return None


def test_extract_review_claims_only_runbook_and_alert():
    assert extract_review_claims({"kind": "Runbook", "evidence": [{}]})[0].mode == "review"
    assert extract_review_claims({"kind": "Alert", "evidence": [{}]})[0].id == "alert/appropriate"
    assert extract_review_claims({"kind": "Flow", "evidence": [{}]}) == []
    assert extract_review_claims({"kind": "Runbook", "evidence": []}) == []  # no evidence -> no claim


def test_worklist_written_with_untrusted_framed_prompts(tmp_path):
    r = _run(tmp_path)
    wl = json.loads((r.root / "challenge" / "worklist.json").read_text())
    assert wl["schema"] == "challenge.worklist/v1"
    arts = {i["artifact"] for i in wl["items"]}
    assert any(a.startswith("Runbook/") for a in arts) and any(a.startswith("Alert/") for a in arts)
    prompt = next(i for i in wl["items"] if i["artifact"] == RUNBOOK)["prompt"]
    assert "UNTRUSTED" in prompt
    assert "supported | unsupported | contradicted" in prompt


def test_apply_contradicted_verdict_rejects_and_moves_file(tmp_path):
    _run(tmp_path)
    layout = _layout(tmp_path)
    assert _status(layout, "Runbook", "order-created-publish-failures") == "needs-review"
    data = {"verdicts": [{"artifact": RUNBOOK, "claimId": "runbook/remediation-safe",
                          "verdict": "contradicted", "reason": "step 3 deletes data without a guard"}]}
    summary = apply_verdicts(layout, data)
    assert summary[0]["new"] == "rejected"
    assert _status(layout, "Runbook", "order-created-publish-failures") == "rejected"


def test_apply_supported_keeps_status_and_records_verdict(tmp_path):
    _run(tmp_path)
    layout = _layout(tmp_path)
    data = {"verdicts": [{"artifact": ALERT, "claimId": "alert/appropriate", "verdict": "supported", "reason": "ok"}]}
    summary = apply_verdicts(layout, data)
    assert summary[0]["new"] == summary[0]["old"] == "needs-review"
    doc = yaml.safe_load((layout.root / "kb" / "needs-review" / "Alert" / "order-created-publish-failures.yaml").read_text())
    assert doc["challengeVerdicts"][0]["verdict"] == "supported"


def test_apply_reports_unknown_artifact(tmp_path):
    _run(tmp_path)
    summary = apply_verdicts(_layout(tmp_path), {"verdicts": [{"artifact": "Runbook/ghost", "verdict": "supported"}]})
    assert summary[0]["result"] == "not-found"
