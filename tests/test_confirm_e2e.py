"""S4 confirm loop end-to-end: a run emits absence claims; a disputed claim the engine re-grounds
moves the false-positive gap to rejected; everything else stands."""

from __future__ import annotations

import json

import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.pipeline.confirm import regate_run
from sre_kb.workspace import RunLayout

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
