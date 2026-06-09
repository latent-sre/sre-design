"""S3 scaffold: the Messaging artifact + Tier-A consumer gaps end-to-end over sample-messaging."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.java_spring import messaging
from sre_kb.pipeline.gap_finder import scaffold_gap
from sre_kb.synth.scaffold import scaffold
from sre_kb.validation import validate_doc

FIXTURE = Path(__file__).parent / "fixtures" / "sample-messaging"


def _run():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-messaging")
    fs = scan(ctx)
    docs = scaffold(fs, ctx)
    gap_docs = [scaffold_gap(f, "sample-messaging") for f in messaging.collect_gaps(ctx, fs)]
    return docs, gap_docs


def test_messaging_artifact_lists_consumers_with_resilience():
    docs, _ = _run()
    msg = [d for d in docs if d["kind"] == "Messaging"]
    assert len(msg) == 1
    assert validate_doc(msg[0]) == []  # schema-valid
    by_channel = {c["channel"]: c for c in msg[0]["spec"]["consumers"]}
    assert by_channel["order.created"]["resilience"]["deadLetter"] is True
    assert by_channel["order.shipped"]["resilience"]["deadLetter"] is False


def test_tier_a_consumer_gaps_verify_through_the_gate():
    _, gap_docs = _run()
    cats = {(d["spec"]["category"], d["spec"]["sourceTier"], d["status"]) for d in gap_docs}
    # Tier-A (sourceTier=ast) consumer gaps reach verified, like the R5 param-completeness gaps
    assert ("consumer-without-dlq", "ast", "verified") in cats
    assert ("non-idempotent-consumer", "ast", "verified") in cats
    assert all(validate_doc(d) == [] for d in gap_docs)
