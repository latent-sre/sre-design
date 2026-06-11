"""S4 confirm loop end-to-end: a run emits absence claims; a disputed claim the engine re-grounds
moves the false-positive gap to rejected; everything else stands."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.pipeline.confirm import regate_run
from sre_kb.workspace import RunLayout

DISABLED_CB = Path(__file__).parent / "fixtures" / "sample-disabled-cb"

# A consumer with a real dead-letter recoverer the engine's annotation/config probe doesn't see, so
# it wrongly asserts consumer-without-dlq — exactly the false positive the confirm loop catches.
_CONSUMER = """\
package x;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
public class C {
    @KafkaListener(topics = "t")
    public void on(Object e) {}
    DeadLetterPublishingRecoverer recoverer(Object template) {
        return new DeadLetterPublishingRecoverer(template);
    }
}
"""
_ANCHOR = "return new DeadLetterPublishingRecoverer(template);"


def _run(tmp_path):
    target = tmp_path / "svc"
    (target / "src/main/java/x").mkdir(parents=True)
    (target / "src/main/java/x/C.java").write_text(_CONSUMER, encoding="utf-8")
    res = run_pipeline(str(target), work_root=str(tmp_path / "w"), run_id="c", to_stage="validate")
    return target, RunLayout(tmp_path / "w", "c"), res


def _kb(layout):
    return {p.parent.name + "/" + p.stem: yaml.safe_load(p.read_text())
            for p in (layout.kb).rglob("*.yaml")}


def test_run_emits_confirm_worklist_and_scan_task(tmp_path):
    _, layout, _ = _run(tmp_path)
    wl = json.loads((layout.root / "confirm" / "boundary-calls.json").read_text())
    claims = {i["category"] for i in wl["items"]}
    assert "consumer-without-dlq" in claims  # the engine's (wrong) absence claim is offered for confirm
    scan = json.loads((layout.root / "scan-worklist.json").read_text())
    assert any(t["id"] == "confirm-boundaries" for t in scan["tasks"])


def test_disputed_claim_regrounds_and_rejects_the_false_gap(tmp_path):
    target, layout, _ = _run(tmp_path)
    name = next(k.split("/", 1)[1] for k in _kb(layout)
                if k.startswith("ResiliencyGap/") and "consumer-without-dlq" in k)
    verdicts = {"verdicts": [{"claimId": "consumer-without-dlq:t", "verdict": "dispute",
                              "anchor": _ANCHOR}]}
    outcomes = regate_run(layout, str(target), verdicts)
    assert any(o.result == "refuted" for o in outcomes)
    # the gap left kb (it was verified) and is now under reports/rejected
    assert f"ResiliencyGap/{name}" not in _kb(layout)
    rejected = (layout.reports / "rejected" / "ResiliencyGap" / f"{name}.yaml")
    assert rejected.exists() and yaml.safe_load(rejected.read_text())["status"] == "rejected"


def test_affirm_leaves_the_gap_verified(tmp_path):
    target, layout, _ = _run(tmp_path)
    before = _kb(layout)
    name = next(k for k in before if k.startswith("ResiliencyGap/") and "consumer-without-dlq" in k)
    outcomes = regate_run(layout, str(target),
                          {"verdicts": [{"claimId": "consumer-without-dlq:t", "verdict": "affirm"}]})
    assert all(o.result != "refuted" for o in outcomes)
    assert name in _kb(layout)  # still present, unchanged


# --- presence direction (present-but-disabled) end-to-end --------------------------------------

def _run_disabled(tmp_path):
    res = run_pipeline(str(DISABLED_CB), work_root=str(tmp_path / "w"), run_id="d", to_stage="validate")
    return RunLayout(tmp_path / "w", "d"), res


def test_run_offers_the_present_breaker_as_a_presence_boundary_call(tmp_path):
    layout, _ = _run_disabled(tmp_path)
    wl = json.loads((layout.root / "confirm" / "boundary-calls.json").read_text())
    presence = [i for i in wl["items"] if i.get("direction") == "presence"]
    assert any(i["claimId"] == "present:circuit-breaker:inventory" for i in presence)


def test_disabled_gap_is_emitted_proactively_and_a_dispute_reconfirms_it(tmp_path):
    """S4c graduated: the proactive collector emits the disabled-resilience gap during the
    plain run — no reviewer dispute needed — and a dispute can only re-confirm it."""
    layout, _ = _run_disabled(tmp_path)
    gap = _kb(layout).get("ResiliencyGap/inventory-disabled-resilience")
    assert gap is not None                         # there BEFORE any confirm verdict
    assert gap["spec"]["category"] == "disabled-resilience" and gap["spec"]["sourceTier"] == "ast"
    assert gap["status"] == "verified"             # byte-grounded to the disabling config line
    verdicts = {"verdicts": [{"claimId": "present:circuit-breaker:inventory", "verdict": "dispute",
                              "anchor": "      inventory:\n        enabled: false"}]}
    outcomes = regate_run(layout, str(DISABLED_CB), verdicts)
    assert any(o.result == "disabled-confirmed" for o in outcomes)
    regapped = _kb(layout).get("ResiliencyGap/inventory-disabled-resilience")
    assert regapped is not None and regapped["status"] == "verified"


def test_disabled_affirm_no_longer_hides_the_disabled_breaker(tmp_path):
    """Before S4c graduated, an affirming (or absent) reviewer hid a disabled breaker; the
    proactive collector closes that hole — the gap survives an affirm verdict."""
    layout, _ = _run_disabled(tmp_path)
    regate_run(layout, str(DISABLED_CB),
               {"verdicts": [{"claimId": "present:circuit-breaker:inventory", "verdict": "affirm"}]})
    gap = _kb(layout).get("ResiliencyGap/inventory-disabled-resilience")
    assert gap is not None and gap["spec"]["rederivation"] == "disabled"


def test_confirm_apply_cli_records_graduation_from_confirms(tmp_path):
    """End-to-end graduation-from-confirms: `confirm-apply` on a confirmed disable writes the
    disabled-resilience confirmation into the (copied) target's graduation tracker."""
    import shutil

    from typer.testing import CliRunner

    from sre_kb.cli import app
    from sre_kb.graduation import GraduationTracker

    target = tmp_path / "svc"
    shutil.copytree(DISABLED_CB, target)               # a writable copy — never the committed fixture
    work = tmp_path / "w"
    run_pipeline(str(target), work_root=str(work), run_id="g", to_stage="validate")
    verdicts = work / "g" / "confirm" / "verdicts.json"
    verdicts.write_text(json.dumps({"verdicts": [
        {"claimId": "present:circuit-breaker:inventory", "verdict": "dispute",
         "anchor": "      inventory:\n        enabled: false"}]}), encoding="utf-8")
    res = CliRunner().invoke(app, ["confirm-apply", "--run", "g", "--work-root", str(work),
                                   "--target", str(target), "--verdicts", str(verdicts)])
    assert res.exit_code == 0, res.output
    assert "graduation: recorded confirmation for disabled-resilience" in res.output
    cat = GraduationTracker.load(target).categories["disabled-resilience"]
    assert cat.confirmed == 1 and cat.false_positives == 0
