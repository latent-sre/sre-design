"""Messaging collector (S3 map-messaging, Tier-A): consumer detection + deterministic gaps."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.java_spring import messaging
from sre_kb.models.facts import FactSet

FIXTURE = Path(__file__).parent / "fixtures" / "sample-messaging"


def _ctx():
    return ScanContext(root=FIXTURE, repo="file://sample-messaging")


def _consumers():
    return {c.attrs["channel"]: c.attrs for c in messaging.collect(_ctx())}


def test_kafka_consumers_detected_with_resilience():
    consumers = _consumers()
    assert set(consumers) == {"order.created", "order.shipped"}
    resilient = consumers["order.created"]
    assert resilient["broker"] == "kafka"
    assert resilient["handler"].endswith("OrderConsumer#onOrderCreated")
    assert resilient["deadLetter"] is True
    assert resilient["deadLetterMechanism"] == "retryable-topic"
    assert resilient["retry"] is True
    assert resilient["idempotentConsumer"] is True


def test_bare_consumer_has_no_resilience():
    bare = _consumers()["order.shipped"]
    assert bare["deadLetter"] is False and bare["deadLetterMechanism"] is None
    assert bare["retry"] is False and bare["idempotentConsumer"] is False


def test_consumer_facts_are_byte_grounded():
    facts = messaging.collect(_ctx())
    assert all(f.evidence.detector == "java_spring.messaging" for f in facts)
    assert all(f.evidence.source_tier == "ast" for f in facts)


def test_tier_a_gaps_for_the_bare_consumer_only():
    ctx = _ctx()
    fs = FactSet()
    fs.add(*messaging.collect(ctx))
    gaps = messaging.collect_gaps(ctx, fs)
    by_cat = {(g.attrs["category"], g.attrs["target"]) for g in gaps}
    # the resilient consumer raises no gaps; the bare one misses both DLQ and idempotency
    assert by_cat == {
        ("consumer-without-dlq", "order.shipped"),
        ("non-idempotent-consumer", "order.shipped"),
    }
    for g in gaps:
        assert g.evidence.source_tier == "ast"            # Tier-A: can verify
        assert g.attrs["rederivation"] == "consumer-resilience"


def test_no_consumers_means_no_facts(tmp_path):
    (tmp_path / "Plain.java").write_text("package x;\npublic class Plain {}\n", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    assert messaging.collect(ctx) == []
    assert messaging.collect_gaps(ctx, FactSet()) == []
