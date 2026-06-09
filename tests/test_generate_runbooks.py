"""Tier-B generate-runbooks re-grounding (coverage #20): the engine drafts a needs-review Runbook only
for an uncovered, real Alert, refusing duplicates and unknown targets, and flags any ungrounded
Kind/name reference in the drafted prose — the closed-world contract applied to runbook authoring."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.pipeline import runbooks_draft
from sre_kb.pipeline.runbooks_draft import RunbookProposal, run_generate_runbooks
from sre_kb.synth.scaffold import scaffold
from sre_kb.tiers import LLM
from sre_kb.validation.provenance import verify_evidence
from sre_kb.validation.structural import validate_doc

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def _result():
    return run_generate_runbooks(str(FIXTURE))


def test_uncovered_alert_is_drafted_as_a_needs_review_runbook():
    res = _result()
    routed = [o for o in res.outcomes if o.result == "routed"]
    assert len(routed) == 1
    assert routed[0].proposal.alert_ref == "create-order-latency-burn-rate"
    assert len(res.docs) == 1
    doc = res.docs[0]
    assert doc["kind"] == "Runbook" and doc["status"] == "needs-review"
    assert doc["spec"]["trigger"]["alertRef"] == "create-order-latency-burn-rate"
    assert doc["spec"]["banner"].startswith("GENERATED")
    assert doc["spec"]["relatedFlow"] == "create-order"        # the related Flow resolved


def test_drafted_runbook_is_fenced_tier_b_and_byte_grounded():
    doc = _result().docs[0]
    assert doc["evidence"][0]["source_tier"] == LLM
    assert doc["provenanceMode"] == "llm-asserted"
    assert doc["unverifiedAgainstLive"] is True
    assert validate_doc(doc) == []
    assert verify_evidence(doc, FIXTURE.resolve()) == []


def test_alert_with_an_existing_runbook_is_refused():
    refuted = next(o for o in _result().outcomes if o.result == "refuted")
    assert refuted.proposal.alert_ref == "order-created-publish-failures"
    assert "already has a runbook" in refuted.note


def test_unknown_alert_target_is_dropped():
    bad = next(o for o in _result().outcomes if o.result == "ungrounded-target")
    assert bad.proposal.alert_ref == "nonexistent-alert"


def test_kept_and_dropped_partition_the_outcomes():
    res = _result()
    assert len(res.kept()) == 1 and len(res.dropped()) == 2


def _docs():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-spring-pcf")
    return ctx, scaffold(scan(ctx), ctx)


def test_ungrounded_prose_reference_is_flagged_but_runbook_still_drafts():
    # A real, uncovered Alert with a hallucinated Dependency/Flow citation in its steps: the runbook
    # still drafts (needs-review) but the bogus reference is named, never silently kept.
    ctx, docs = _docs()
    p = RunbookProposal(
        alert_ref="create-order-latency-burn-rate",
        diagnosis=("Inspect Dependency/ghost-cache for latency",),
        remediation=("Restart Flow/nope",),
    )
    res = runbooks_draft.reground(ctx, [p], docs, "sample-spring-pcf")
    assert [o.result for o in res.outcomes] == ["routed"]
    assert set(res.outcomes[0].ungrounded_refs) == {"Dependency/ghost-cache", "Flow/nope"}
    assert len(res.docs) == 1                                  # drafted despite the flagged refs


def test_a_second_proposal_for_the_same_alert_is_refused():
    # Two drafts for one Alert would collide on artifact name — the second is refused like a duplicate.
    ctx, docs = _docs()
    p = RunbookProposal(alert_ref="create-order-latency-burn-rate", remediation=("step",))
    res = runbooks_draft.reground(ctx, [p, p], docs, "sample-spring-pcf")
    assert [o.result for o in res.outcomes] == ["routed", "refuted"]
    assert len(res.docs) == 1


def test_no_proposals_file_is_a_clean_no_op(tmp_path):
    res = run_generate_runbooks(str(tmp_path))
    assert res.outcomes == [] and res.docs == []


def test_malformed_proposals_file_self_gates(tmp_path):
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "runbook-proposals.json").write_text("{ not json", encoding="utf-8")
    assert run_generate_runbooks(str(tmp_path)).outcomes == []
