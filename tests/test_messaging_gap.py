"""S3 Tier-B: messaging-resilience judgment categories in the gap-finder.

`missing-poison-pill-handling` refutes against the engine's own consumer facts (a dead-letter route
handles it); `unordered-consumer` and `missing-saga-compensation` are judgment routed to review.
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.llm import gap_finder
from sre_kb.collectors.llm.gap_finder import Proposal

FIXTURE = Path(__file__).parent / "fixtures" / "sample-messaging"
_ANCHOR_SHIPPED = '@KafkaListener(topics = "order.shipped", groupId = "orders")'
_ANCHOR_ORDER = '@KafkaListener(topics = "order.created", groupId = "orders")'


def _ctx():
    return ScanContext(root=FIXTURE, repo="file://sample-messaging")


def _fs():
    ctx = _ctx()
    return scan(ctx)


def test_messaging_categories_registered():
    cats = gap_finder.gap_categories()
    assert {"unordered-consumer", "missing-poison-pill-handling", "missing-saga-compensation"} <= cats


def test_unordered_consumer_routes_to_review():
    res = gap_finder.collect_from_proposals(
        _ctx(), [Proposal("unordered-consumer", _ANCHOR_SHIPPED, target="order.shipped")], fs=_fs())
    assert len(res.facts) == 1
    assert res.facts[0].evidence.source_tier == "llm"
    assert res.facts[0].attrs["rederivation"] == "judgment"


def test_poison_pill_refuted_when_consumer_has_dlq():
    # order.created's consumer has @RetryableTopic -> dead-letter route -> the gap is refuted
    res = gap_finder.collect_from_proposals(
        _ctx(), [Proposal("missing-poison-pill-handling", _ANCHOR_ORDER, target="order.created")],
        fs=_fs())
    assert res.facts == []
    assert res.outcomes[0].result == "refuted"


def test_poison_pill_routes_when_consumer_has_no_dlq():
    # order.shipped's consumer has no dead-letter route -> the gap routes to review
    res = gap_finder.collect_from_proposals(
        _ctx(), [Proposal("missing-poison-pill-handling", _ANCHOR_SHIPPED, target="order.shipped")],
        fs=_fs())
    assert len(res.facts) == 1
    assert res.facts[0].evidence.source_tier == "llm"


def test_saga_compensation_is_permanent_judgment():
    res = gap_finder.collect_from_proposals(
        _ctx(),
        [Proposal("missing-saga-compensation", _ANCHOR_ORDER, target="order.created")],
        fs=_fs())
    # never refuted by a fact — saga has no deterministic ground truth, always routes
    assert len(res.facts) == 1
    assert res.facts[0].attrs["rederivation"] == "judgment"
