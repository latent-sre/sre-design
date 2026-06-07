"""Recall eval for the LLM gap-finder (HYBRID-PLAN §7.9 — the dual of §7.3's precision eval).

A sample with a *known planted gap* (a payments client call with no timeout) plus two traps in
the simulated LLM output: a FALSE gap on a call that already has a timeout, and a HALLUCINATED gap
whose quoted excerpt doesn't exist. The contract under test:

  recall        the planted gap IS surfaced;
  non-circular  the engine REFUTES the false gap (shared signature fires) and DROPS the
                hallucinated one (no verbatim anchor) — the LLM can neither assert a gap that
                isn't there nor fabricate a citation;
  grounded      the surfaced gap carries a real, hash-checkable path:line:excerptHash, source_tier=llm;
  no auto-verify every LLM-proposed gap lands needs-review, never verified.
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.llm import gap_finder
from sre_kb.pipeline.gap_finder import run_gap_finder
from sre_kb.tiers import LLM, artifact_tier
from sre_kb.validation.provenance import verify_evidence
from sre_kb.validation.structural import validate_doc

FIXTURE = Path(__file__).parent / "fixtures" / "sample-gap-finder"


def _ctx() -> ScanContext:
    return ScanContext(root=FIXTURE, repo="file://sample-gap-finder", commit=LOCAL_COMMIT)


# --------------------------------------------------------------- collector-level recall

def test_recall_surfaces_planted_gap_and_drops_the_traps():
    res = gap_finder.collect(_ctx())

    # RECALL: exactly the planted payments timeout gap survives.
    confirmed = res.confirmed()
    assert len(confirmed) == 1, [(o.proposal.target, o.result) for o in res.outcomes]
    gap = confirmed[0]
    assert gap.proposal.target == "payments-api"
    assert gap.proposal.category == "missing-timeout"
    assert gap.path.endswith("PaymentsClient.java")

    # NON-CIRCULAR: the two traps are dropped, each for the right reason.
    by_target = {o.proposal.target: o.result for o in res.outcomes}
    assert by_target["shipping-api"] == "refuted"      # @TimeLimiter present -> signature fires
    assert by_target["refunds-api"] == "unlocatable"   # excerpt doesn't exist -> no fabricated cite


def test_surfaced_gap_is_byte_grounded_and_tier_llm():
    res = gap_finder.collect(_ctx())
    [fact] = res.facts

    # The engine stamped the citation itself; it must hash-check against the bytes.
    doc_like = {"evidence": [fact.evidence.model_dump(mode="json")]}
    assert verify_evidence(doc_like, FIXTURE) == []
    assert fact.evidence.detector == "llm.gap_finder"
    assert fact.evidence.source_tier == LLM           # Tier-B rides on evidence (main's seam)
    assert fact.attrs["rederivation"] == "confirmed"
    # The honest-negative trail names where the engine looked before asserting the absence.
    assert any("PaymentsClient.java" in c for c in fact.attrs["checked"])


# --------------------------------------------------------------- pipeline-level gating

def test_nothing_the_llm_proposes_auto_verifies():
    run = run_gap_finder(str(FIXTURE), service="checkout")

    assert run.by_status == {"needs-review": 1}  # the one planted gap, fenced to review
    [doc] = run.docs
    assert doc["kind"] == "ResiliencyGap"
    assert doc["status"] == "needs-review"          # never verified
    assert validate_doc(doc) == []                  # but it IS a schema-valid artifact
    assert verify_evidence(doc, FIXTURE) == []      # with grounded provenance
    assert doc["confidence"] < 0.7                  # below the verified floor even if status were raised
    assert doc["spec"]["sourceTier"] == "llm"
    assert doc["provenanceMode"] == "llm-asserted"
    assert doc["unverifiedAgainstLive"] is True
    assert artifact_tier(doc) == LLM                # rolls up to Tier-B
    assert doc["spec"]["category"] == "missing-timeout"
    assert doc["spec"]["target"] == "payments-api"


def test_no_proposals_file_is_a_quiet_no_op():
    # Self-gating: a target with no gap-proposals.json yields nothing (no crash, no noise).
    run = run_gap_finder(str(FIXTURE.parent / "sample-spring-pcf"), service="order")
    assert run.docs == []
    assert run.by_status == {}


# --------------------------------------------------------------- re-derivation realism

def test_refutation_probe_generalizes_to_the_real_dotnet_gap():
    """The same signature-based probe, pointed at the bundled .NET sample, confirms a genuine
    missing timeout (Polly breaker, no timeout) and refutes the Spring client with @TimeLimiter."""
    dotnet = Path(__file__).parent / "fixtures" / "sample-dotnet-steeltoe"
    ctx = ScanContext(root=dotnet, repo="file://net", commit=LOCAL_COMMIT)
    verdict, _, _ = gap_finder._rederive(ctx, "src/Clients/InventoryClient.cs", 22, 22, "missing-timeout")
    assert verdict == "confirmed"

    spring = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
    sctx = ScanContext(root=spring, repo="file://spring", commit=LOCAL_COMMIT)
    rel = "src/main/java/com/acme/order/client/InventoryClient.java"
    sverdict, _, _ = gap_finder._rederive(sctx, rel, 26, 26, "missing-timeout")
    assert sverdict == "refuted"
