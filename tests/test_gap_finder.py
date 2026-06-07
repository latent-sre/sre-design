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
from sre_kb.collectors.llm.gap_finder import Proposal
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


_NOTIFY = 'restTemplate.postForObject(baseUrl + "/notify", new Event(orderId), Void.class);'
_CHARGE = 'return restTemplate.postForObject(baseUrl + "/charge", new Charge(orderId, amountCents), Receipt.class);'


# --------------------------------------------------------------- second probe + noise budget

def test_unguarded_critical_dependency_probe():
    # NotificationsClient has no breaker/fallback/timeout (and no config) -> confirmed.
    # PaymentsClient.charge carries @CircuitBreaker + a fallback -> the probe refutes it.
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("unguarded-critical-dependency", _NOTIFY, target="notifications", severity="high"),
        Proposal("unguarded-critical-dependency", _CHARGE, target="payments-api", severity="high"),
    ])
    by_target = {o.proposal.target: o.result for o in res.outcomes}
    assert by_target["notifications"] == "confirmed"
    assert by_target["payments-api"] == "refuted"


def test_config_probe_is_target_scoped():
    # application.yml has a circuit-breaker block for `payments`/`shipping` but NOT `notifications`.
    # A whole-file probe would wrongly refute the notifications gap; the target-scoped probe must not.
    [out] = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("unguarded-critical-dependency", _NOTIFY, target="notifications", severity="high"),
    ]).outcomes
    assert out.result == "confirmed"


def test_noise_budget_caps_lower_severity_first():
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("unguarded-critical-dependency", _NOTIFY, target="notifications", severity="medium"),
        Proposal("missing-timeout", _CHARGE, target="payments-api", severity="high"),
    ], max_candidates=1)
    assert len(res.facts) == 1
    [kept] = res.confirmed()
    assert kept.proposal.target == "payments-api"           # high severity kept
    assert any(o.result == "capped" for o in res.outcomes)  # medium dropped by the budget


_LEDGER = "ledgerRepository.save(new Entry(orderId, amountCents));"


# --------------------------------------------------------------- confirmation probe + graduation

def test_swallowed_failure_confirms_and_graduates_to_tier_a():
    # A swallowed DB write the collectors don't emit (they only emit swallow facts for Kafka).
    # The confirmation probe re-derives it deterministically -> graduates to Tier-A (source_tier=ast).
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("swallowed-failure", _LEDGER, target="ledger", severity="high"),
    ])
    [out] = res.outcomes
    assert out.result == "confirmed"
    [fact] = res.facts
    assert fact.evidence.source_tier == "ast"          # graduated, not llm
    assert fact.evidence.detector == "gap_finder.swallowed-failure"


def test_swallowed_failure_dropped_when_rule_does_not_fire():
    # NotificationsClient's call is NOT in a try/catch -> the swallow rule doesn't fire -> dropped.
    # The LLM can't assert a swallow the engine can't reproduce.
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("swallowed-failure", _NOTIFY, target="notifications", severity="high"),
    ])
    assert res.facts == []
    assert res.outcomes[0].result == "refuted"


def test_graduated_swallow_reaches_verified_through_the_gate(tmp_path):
    import json
    props = tmp_path / "gap-proposals.json"
    props.write_text(json.dumps({"proposals": [
        {"category": "swallowed-failure", "target": "ledger", "severity": "high", "anchor": _LEDGER},
    ]}), encoding="utf-8")
    run = run_gap_finder(str(FIXTURE), proposals_path=str(props), service="checkout")
    assert run.by_status == {"verified": 1}            # graduated Tier-A finding clears the gate
    [doc] = run.docs
    assert doc["spec"]["sourceTier"] == "ast"
    assert doc["spec"]["category"] == "swallowed-failure"
    assert doc["provenanceMode"] == "deterministic"
    assert "unverifiedAgainstLive" not in doc          # a byte-grounded presence, not an absence
    assert validate_doc(doc) == []
    assert verify_evidence(doc, FIXTURE) == []         # cites the real swallowing catch block


_REPORT_JOB = "public void emitDailyReconciliation() {"


def test_undocumented_job_confirms_via_scheduled_signature():
    # @Scheduled fires the `scheduled` signature at the pointer -> engine-confirmed -> Tier-A.
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("undocumented-job", _REPORT_JOB, target="report-job", severity="medium"),
    ])
    [out] = res.outcomes
    assert out.result == "confirmed"
    [fact] = res.facts
    assert fact.evidence.source_tier == "ast"          # graduated like the swallow probe
    assert fact.attrs["category"] == "undocumented-job"


def test_undocumented_job_dropped_when_not_scheduled():
    # A plain method with no scheduler annotation -> signature doesn't fire -> dropped.
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("undocumented-job", _NOTIFY, target="notifications", severity="medium"),
    ])
    assert res.facts == []
    assert res.outcomes[0].result == "refuted"


def test_judgment_category_is_routed_not_dropped():
    # data-loss-path has no deterministic probe (§7.9 judgment call). It still grounds the citation
    # and is surfaced as a routed Tier-B candidate — not dropped, never confirmed.
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("data-loss-path", _CHARGE, target="payments-api", severity="high"),
    ])
    [out] = res.outcomes
    assert out.result == "routed"
    assert res.kept() and not res.confirmed()
    [fact] = res.facts
    assert fact.evidence.source_tier == "llm" and fact.attrs["rederivation"] == "judgment"


def test_judgment_gap_lands_needs_review_never_verified(tmp_path):
    import json
    props = tmp_path / "g.json"
    props.write_text(json.dumps({"proposals": [
        {"category": "missing-idempotency", "target": "payments-api", "severity": "high", "anchor": _CHARGE},
    ]}), encoding="utf-8")
    run = run_gap_finder(str(FIXTURE), proposals_path=str(props), service="checkout")
    assert run.by_status == {"needs-review": 1}
    [doc] = run.docs
    assert doc["spec"]["sourceTier"] == "llm"
    assert doc["spec"]["rederivation"] == "judgment"
    assert validate_doc(doc) == []


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
    verdict, _, _ = gap_finder._rederive(ctx, "src/Clients/InventoryClient.cs", 22, 22, "missing-timeout", "inventory")
    assert verdict == "confirmed"

    spring = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
    sctx = ScanContext(root=spring, repo="file://spring", commit=LOCAL_COMMIT)
    rel = "src/main/java/com/acme/order/client/InventoryClient.java"
    sverdict, _, _ = gap_finder._rederive(sctx, rel, 26, 26, "missing-timeout", "inventory")
    assert sverdict == "refuted"
