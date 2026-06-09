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
