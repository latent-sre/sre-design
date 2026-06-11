"""S4 confirm loop: the engine re-grounds a skill's disputes of its own absence claims.

A dispute can only DROP a gap, and only by pointing at REAL code where the engine's own signature
fires in the gap's scope — it can't fabricate. Affirm / unlocatable / out-of-scope / unconfirmed all
leave the gap standing.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.pipeline import confirm

_CONSUMER = """\
package x;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.annotation.RetryableTopic;
public class C {
    @RetryableTopic(attempts = "3")
    @KafkaListener(topics = "t")
    public void on(Object e) {}
}
"""


def _ctx_and_gap(tmp_path, *, line=6):
    (tmp_path / "C.java").write_text(_CONSUMER, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    # the engine (wrongly) asserted the consumer has no dead-letter route at the @KafkaListener line
    gap = Fact(
        "resiliency.gap",
        {"category": "consumer-without-dlq", "target": "t", "severity": "high",
         "checked": ["C.java"], "rederivation": "consumer-resilience"},
        ctx.evidence("C.java", line, line, "java_spring.messaging"),
        Symbol("x.C#on", "method"),
    )
    return ctx, gap


def _verdict(claim_id, verdict, anchor=None):
    return {"verdicts": [{"claimId": claim_id, "verdict": verdict, "anchor": anchor}]}


def test_worklist_lists_confirmable_absence_gaps(tmp_path):
    _, gap = _ctx_and_gap(tmp_path)
    wl = confirm.build_confirm_worklist("r1", [gap])
    assert wl["schema"] == confirm.SCHEMA
    assert len(wl["items"]) == 1
    item = wl["items"][0]
    assert item["category"] == "consumer-without-dlq" and item["concern"] == ["dead-letter"]


def test_dispute_with_real_mechanism_refutes_the_gap(tmp_path):
    ctx, gap = _ctx_and_gap(tmp_path)
    cid = confirm._claim_id(gap)
    out = confirm.apply_confirm(ctx, [gap], _verdict(cid, "dispute", '@RetryableTopic(attempts = "3")'))
    assert len(out) == 1 and out[0].result == "refuted"


def test_affirm_leaves_the_gap_standing(tmp_path):
    ctx, gap = _ctx_and_gap(tmp_path)
    out = confirm.apply_confirm(ctx, [gap], _verdict(confirm._claim_id(gap), "affirm"))
    assert out[0].result == "affirmed"


def test_dispute_without_a_real_mechanism_is_unconfirmed(tmp_path):
    ctx, gap = _ctx_and_gap(tmp_path)
    # quote a real line that carries no dead-letter signature -> dispute rejected, gap stands
    out = confirm.apply_confirm(
        ctx, [gap], _verdict(confirm._claim_id(gap), "dispute", "public void on(Object e) {}"))
    assert out[0].result == "dispute-unconfirmed"


def test_fabricated_anchor_is_unlocatable(tmp_path):
    ctx, gap = _ctx_and_gap(tmp_path)
    out = confirm.apply_confirm(
        ctx, [gap], _verdict(confirm._claim_id(gap), "dispute", "@RetryableTopic(fabricated = true)"))
    assert out[0].result == "dispute-unlocatable"


def test_only_tier_a_absence_gaps_are_confirmable(tmp_path):
    ctx, gap = _ctx_and_gap(tmp_path)
    # an LLM-tier judgment gap is not a confirmable engine boundary call
    llm_gap = Fact("resiliency.gap", {"category": "data-loss-path", "target": "x"},
                   ctx.evidence("C.java", 6, 6, "llm.gap_finder", source_tier="llm"))
    assert confirm.confirmable(gap) and not confirm.confirmable(llm_gap)
    assert confirm.build_confirm_worklist("r", [llm_gap])["items"] == []


# --- presence direction (present-but-disabled) -------------------------------------------------

_BREAKER = """\
package x;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
public class InventoryClient {
    @CircuitBreaker(name = "inventory", fallbackMethod = "fb")
    public void reserve(String sku) {}
}
"""
_CONFIG = """\
resilience4j:
  circuitbreaker:
    instances:
      inventory:
        enabled: false
"""


def _ctx_and_breaker(tmp_path):
    (tmp_path / "InventoryClient.java").write_text(_BREAKER, encoding="utf-8")
    (tmp_path / "application.yml").write_text(_CONFIG, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    pf = Fact("resiliency.circuitbreaker", {"name": "inventory", "target": "reserve"},
              ctx.evidence("InventoryClient.java", 4, 4, "java_spring.resiliency", source_tier="ast"))
    return ctx, pf


def test_worklist_lists_presence_boundary_calls(tmp_path):
    ctx, pf = _ctx_and_breaker(tmp_path)
    wl = confirm.build_confirm_worklist("r", [], [pf])
    item = next(i for i in wl["items"] if i.get("direction") == "presence")
    assert item["claimId"] == "present:circuit-breaker:inventory"
    assert item["concern"] == ["circuit-breaker"] and item["target"] == "inventory"


def test_only_named_tier_a_mechanisms_are_presence_confirmable(tmp_path):
    ctx, pf = _ctx_and_breaker(tmp_path)
    nameless = Fact("resiliency.circuitbreaker", {"name": "", "target": "x"},
                    ctx.evidence("InventoryClient.java", 4, 4, "java_spring.resiliency", source_tier="ast"))
    assert confirm.presence_confirmable(pf) and not confirm.presence_confirmable(nameless)


def test_dispute_with_disable_config_confirms_and_builds_a_tier_a_gap(tmp_path):
    ctx, pf = _ctx_and_breaker(tmp_path)
    out = confirm.apply_confirm(
        ctx, [], _verdict("present:circuit-breaker:inventory", "dispute",
                          "      inventory:\n        enabled: false"), [pf])[0]
    assert out.result == "disabled-confirmed" and out.gap is not None
    assert out.gap.attrs["category"] == "disabled-resilience"
    assert out.gap.attrs["target"] == "inventory"
    assert out.gap.evidence.source_tier == "ast"          # engine-re-derived → graduates to Tier-A


def test_presence_affirm_leaves_the_mechanism_standing(tmp_path):
    ctx, pf = _ctx_and_breaker(tmp_path)
    out = confirm.apply_confirm(ctx, [], _verdict("present:circuit-breaker:inventory", "affirm"), [pf])[0]
    assert out.result == "affirmed" and out.gap is None


def test_presence_dispute_naming_the_wrong_instance_is_out_of_scope(tmp_path):
    ctx, pf = _ctx_and_breaker(tmp_path)
    # a disable for a DIFFERENT instance must not confirm a disable on `inventory`.
    (tmp_path / "application.yaml").write_text("payments:\n  enabled: false\n", encoding="utf-8")
    out = confirm.apply_confirm(
        ctx, [], _verdict("present:circuit-breaker:inventory", "dispute",
                          "payments:\n  enabled: false"), [pf])[0]
    assert out.result == "dispute-out-of-scope" and out.gap is None


def test_presence_dispute_without_a_disable_signal_is_unconfirmed(tmp_path):
    ctx, pf = _ctx_and_breaker(tmp_path)
    # an anchor that names the instance but carries no `enabled: false` cannot confirm a disable.
    (tmp_path / "application.properties").write_text(
        "resilience4j.circuitbreaker.instances.inventory.failure-rate-threshold=50\n", encoding="utf-8")
    out = confirm.apply_confirm(
        ctx, [], _verdict("present:circuit-breaker:inventory", "dispute",
                          "resilience4j.circuitbreaker.instances.inventory.failure-rate-threshold=50"), [pf])[0]
    assert out.result == "dispute-unconfirmed" and out.gap is None


# --- graduation-from-confirms ------------------------------------------------------------------

def _disabled_outcome(tmp_path):
    ctx, pf = _ctx_and_breaker(tmp_path)
    return confirm.apply_confirm(
        ctx, [], _verdict("present:circuit-breaker:inventory", "dispute",
                          "      inventory:\n        enabled: false"), [pf])


def test_confirmed_disable_accrues_toward_graduation(tmp_path):
    from sre_kb.graduation import GraduationTracker

    outs = _disabled_outcome(tmp_path)
    rec = confirm.record_confirm_graduation(tmp_path, outs, run_id="r")
    assert rec == {"disabled-resilience": "confirmation"}
    cat = GraduationTracker.load(tmp_path).categories["disabled-resilience"]
    assert cat.confirmed == 1 and cat.false_positives == 0
    assert cat.anchors and cat.anchors[0].endswith(":4")  # the disabling config line


def test_refuted_absence_records_a_false_positive(tmp_path):
    from sre_kb.graduation import GraduationTracker
    from sre_kb.pipeline.confirm import ConfirmOutcome

    out = ConfirmOutcome("missing-timeout:x", "ResiliencyGap/x", "refuted", category="missing-timeout")
    rec = confirm.record_confirm_graduation(tmp_path, [out], run_id="r")
    assert rec == {"missing-timeout": "false-positive"}
    assert GraduationTracker.load(tmp_path).categories["missing-timeout"].false_positives == 1


def test_affirms_and_unconfirmed_disputes_carry_no_graduation_signal(tmp_path):
    from sre_kb.pipeline.confirm import ConfirmOutcome

    neutral = [
        ConfirmOutcome("a", "ResiliencyGap/a", "affirmed", category="missing-timeout"),
        ConfirmOutcome("b", "ResiliencyGap/b", "dispute-unconfirmed", category="missing-timeout"),
        ConfirmOutcome("c", "ResiliencyPattern/c", "affirmed", category="disabled-resilience"),
    ]
    assert confirm.record_confirm_graduation(tmp_path, neutral, run_id="r") == {}
    # nothing changed -> the tracker file is never written
    assert not (tmp_path / ".sre" / "graduation-tracker.yaml").exists()


def test_disabled_resilience_is_a_confirm_loop_graduation_category():
    assert "disabled-resilience" in confirm.confirm_emitted_categories()


def test_draft_signature_for_disabled_resilience_describes_a_proactive_collector():
    from sre_kb.graduation import ConfirmedCategory, draft_signature

    cat = ConfirmedCategory(category="disabled-resilience", confirmed=5)
    draft = draft_signature(cat, (), known=True)
    assert "resiliency_params" in draft  # the proactive collector exists; extend, don't regex
