"""Recall eval for the LLM gap-finder (HYBRID-PLAN §7.9).

The checked-in fixture carries a real assistant proposal file with four planted gaps. Separate
control proposals exercise the non-circular contract: the engine refutes a false timeout gap and
drops an unlocatable anchor, so the model can neither assert a gap that is not there nor fabricate
a citation.
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


def test_collect_tolerates_a_malformed_proposals_file(tmp_path):
    """A broken .sre/gap-proposals.json must self-gate to an empty result, not abort the scan (the
    YAML collectors tolerate bad input; the scan path should too)."""
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "gap-proposals.json").write_text("{ not json", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x", commit=LOCAL_COMMIT)
    res = gap_finder.collect(ctx)
    assert res.facts == [] and res.outcomes == []


def test_locate_requires_whole_line_not_substring(tmp_path):
    """A verbatim anchor must match a whole source line, not merely be a substring of one — else a
    near-miss could locate to the wrong span yet still hash-validate."""
    from sre_kb.collectors.llm.gap_finder import _locate

    (tmp_path / "A.java").write_text("class A {\n    return xs;\n}\n", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x", commit=LOCAL_COMMIT)
    assert _locate(ctx, "return x") is None             # substring of `return xs;` must NOT match
    assert _locate(ctx, "return xs;") == ("A.java", 2, 2)  # the exact whole line does


def _ctx() -> ScanContext:
    return ScanContext(root=FIXTURE, repo="file://sample-gap-finder", commit=LOCAL_COMMIT)


# --------------------------------------------------------------- collector-level recall

def test_recall_surfaces_checked_in_gap_proposals():
    res = gap_finder.collect(_ctx())

    by_key = {(o.proposal.category, o.proposal.target): o.result for o in res.outcomes}
    assert by_key == {
        ("missing-timeout", "payments-api"): "confirmed",
        ("unguarded-critical-dependency", "notifications-api"): "confirmed",
        ("swallowed-failure", "ledgerRepository"): "confirmed",
        ("undocumented-job", "emitDailyReconciliation"): "confirmed",
        # the planted out-of-taxonomy gap rides the open-discovery channel
        ("fallback-masks-failure", "payments-api"): "routed",
    }
    assert len(res.facts) == 5


def test_refutes_timeout_control_and_drops_unlocatable_anchor():
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal(
            "missing-timeout",
            'return restTemplate.getForObject(baseUrl + "/quote?order=" + orderId, Quote.class);',
            target="shipping-api",
            severity="high",
        ),
        Proposal("missing-timeout", "return refunds.charge();", target="refunds-api"),
    ])
    by_target = {o.proposal.target: o.result for o in res.outcomes}
    assert by_target["shipping-api"] == "refuted"
    assert by_target["refunds-api"] == "unlocatable"
    assert res.facts == []


def test_surfaced_gap_is_byte_grounded_and_tier_llm():
    res = gap_finder.collect(_ctx())
    fact = next(f for f in res.facts if f.attrs["category"] == "missing-timeout")

    # The engine stamped the citation itself; it must hash-check against the bytes.
    doc_like = {"evidence": [fact.evidence.model_dump(mode="json")]}
    assert verify_evidence(doc_like, FIXTURE) == []
    assert fact.evidence.detector == "llm.gap_finder"
    assert fact.evidence.source_tier == LLM           # Tier-B rides on evidence (main's seam)
    assert fact.attrs["rederivation"] == "confirmed"
    # The honest-negative trail names where the engine looked before asserting the absence.
    assert any("PaymentsClient.java" in c for c in fact.attrs["checked"])


# --------------------------------------------------------------- pipeline-level gating

def test_refutation_gaps_stay_needs_review_while_confirmation_gaps_verify():
    run = run_gap_finder(str(FIXTURE), service="checkout")

    assert run.by_status == {"needs-review": 3, "verified": 2}  # +1: the routed novel gap
    doc = next(d for d in run.docs if d["metadata"]["name"] == "payments-api-missing-timeout")
    assert doc["kind"] == "ResiliencyGap"
    assert doc["status"] == "needs-review"
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


def test_config_scope_matches_whole_instance_token_not_prefix():
    # §9.5 ⑤: a substring scope let `payments` match a *different* `payments-api` config block, so a
    # timeout there wrongly refuted a real gap on `payments`. The whole-token check must not.
    cfg = "resilience4j.timelimiter.instances.payments-api.timeoutDuration: 2s\n"
    assert gap_finder._name_in_text("payments-api", cfg) is True       # the real instance scopes in
    assert gap_finder._name_in_text("payments", cfg) is False          # a prefix of a *different* one must not
    assert gap_finder._name_in_text("payments", "instances.payments.timeoutDuration: 2s") is True


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


_BPRESS = "events.onBackpressureBuffer(256).subscribe(this::process);"


def test_load_shed_backpressure_are_known_judgment_categories():
    # N5: the new vocab is registered so the graduation loop's confirm-gap accepts a verdict on it.
    assert {"missing-backpressure", "missing-load-shedding"} <= gap_finder.gap_categories()


def test_missing_backpressure_routes_when_unbounded_and_refutes_when_present(tmp_path):
    # Routed: the cited type has no backpressure mechanism -> judgment, surfaced to the oracle.
    routed = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("missing-backpressure", _CHARGE, target="payments", severity="high"),
    ])
    [out] = routed.outcomes
    assert out.result == "routed"
    [fact] = routed.facts
    assert fact.evidence.source_tier == "llm" and fact.attrs["rederivation"] == "judgment"

    # Refuted: a type that already bounds the stream -> the backpressure signature fires in scope ->
    # dropped, never spent on the oracle (the same shared-signature seam the refutation probes use).
    (tmp_path / "Ingest.java").write_text(
        "package com.acme;\n"
        "public class Ingest {\n"
        "    public void run(reactor.core.publisher.Flux<Job> events) {\n"
        f"        {_BPRESS}\n"
        "    }\n"
        "    void process(Job j) {}\n"
        "}\n",
        encoding="utf-8",
    )
    ctx = ScanContext(root=tmp_path, repo="file://bp", commit=LOCAL_COMMIT)
    refuted = gap_finder.collect_from_proposals(ctx, [
        Proposal("missing-backpressure", _BPRESS, target="ingest", severity="high"),
    ])
    [r] = refuted.outcomes
    assert r.result == "refuted"
    assert refuted.facts == []


def test_missing_load_shedding_refuted_when_shedder_present(tmp_path):
    # A semaphore tryAcquire that returns busy IS a load-shedder -> the gap doesn't hold -> refuted.
    anchor = "if (!permits.tryAcquire()) return Resp.busy();"
    (tmp_path / "Gate.java").write_text(
        "package com.acme;\n"
        "import java.util.concurrent.Semaphore;\n"
        "public class Gate {\n"
        "    private final Semaphore permits = new Semaphore(100);\n"
        "    public Resp handle(Req r) {\n"
        f"        {anchor}\n"
        "        return serve(r);\n"
        "    }\n"
        "    Resp serve(Req r) { return Resp.ok(); }\n"
        "}\n",
        encoding="utf-8",
    )
    ctx = ScanContext(root=tmp_path, repo="file://ls", commit=LOCAL_COMMIT)
    res = gap_finder.collect_from_proposals(ctx, [
        Proposal("missing-load-shedding", anchor, target="gate", severity="high"),
    ])
    [out] = res.outcomes
    assert out.result == "refuted"
    assert res.facts == []


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


# --------------------------------------------------------------- #42: cross-stack anchor locating

def _cross_stack_repo(tmp_path: Path) -> Path:
    """A repo whose resiliency mechanisms live in Go/Node/nginx files — outside the Java/C#/Python
    source globs. The judgment vocab (backpressure/load-shed) reasons about exactly these."""
    (tmp_path / "svc.go").write_text(
        "package svc\n"
        "func produce(in chan Job) {\n"
        "\tout := make(chan Job)\n"          # unbounded channel -> a real backpressure gap
        "\tfor j := range in { out <- j }\n"
        "}\n",
        encoding="utf-8",
    )
    (tmp_path / "stream.js").write_text(
        "const { Readable } = require('stream');\n"
        "const src = new Readable();\n"      # no highWaterMark -> unbounded
        "src.on('data', (c) => sink.write(c));\n",
        encoding="utf-8",
    )
    (tmp_path / "api.conf").write_text(
        "location /api {\n"
        "    proxy_pass http://backend;\n"   # no limit_req -> no load shedding
        "}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_judgment_anchor_in_go_node_nginx_is_located_not_dropped(tmp_path):
    """#42: a judgment-call gap whose anchor lives in a Go/Node/nginx file must locate and route to
    the oracle. Before widening the locate globs these were always dropped `unlocatable`, so the
    cross-stack judgment categories silently did nothing."""
    ctx = ScanContext(root=_cross_stack_repo(tmp_path), repo="file://x", commit=LOCAL_COMMIT)
    cases = [
        ("missing-backpressure", "out := make(chan Job)"),   # Go
        ("unbounded-resource", "const src = new Readable();"),  # Node
        ("missing-load-shedding", "proxy_pass http://backend;"),  # nginx
    ]
    for category, anchor in cases:
        res = gap_finder.collect_from_proposals(ctx, [Proposal(category, anchor, target="svc", severity="high")])
        [out] = res.outcomes
        assert out.result == "routed", f"{category} @ {anchor!r} -> {out.result} (expected routed)"
        [fact] = res.facts
        assert fact.evidence.source_tier == "llm" and fact.attrs["rederivation"] == "judgment"


def test_go_confirming_anchor_locates_but_is_not_confirmed_without_the_rule(tmp_path):
    """Go now has an engine AST, so a confirming-category anchor in a `.go` file locates and the probe
    runs — but the gap is kept only if the rule actually fires. A `make(chan)` is not a scheduled job,
    so the undocumented-job confirmation refutes it (located, probed, dropped) rather than falsely
    keeping it: the no-false-confirm invariant holds, now via refute instead of unlocatable."""
    ctx = ScanContext(root=_cross_stack_repo(tmp_path), repo="file://x", commit=LOCAL_COMMIT)
    res = gap_finder.collect_from_proposals(
        ctx, [Proposal("undocumented-job", "out := make(chan Job)", target="svc", severity="medium")]
    )
    assert res.outcomes[0].result == "refuted"
    assert res.facts == []  # nothing confirmed or kept


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


# --------------------------------------------------------------- open discovery (novel categories)

_SHIP = 'return restTemplate.getForObject(baseUrl + "/quote?order=" + orderId, Quote.class);'


def test_out_of_taxonomy_category_is_routed_as_novel_not_dropped():
    """The open-discovery channel (SCOPE §6): a category nobody anticipated still lands — locate-
    grounded, marked `novel` with the proposed name as data, routed to review. Before this channel
    it died as `unconfirmable` and the LLM could not surface anything outside the taxonomy."""
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("missing-cache-invalidation", _SHIP, target="shipping-api", severity="high"),
    ])
    [out] = res.outcomes
    assert out.result == "routed" and "novel" in out.note
    [fact] = res.facts
    assert fact.attrs["category"] == "novel"
    assert fact.attrs["proposedCategory"] == "missing-cache-invalidation"
    assert fact.attrs["rederivation"] == "novel"
    assert fact.evidence.source_tier == LLM  # never graduates without a probe


def test_novel_with_unslug_name_or_fabricated_anchor_is_dropped():
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("Not A Slug!!", _SHIP, target="shipping-api"),          # garbage name
        Proposal("novel", _SHIP, target="shipping-api"),                 # reserved marker
        Proposal("plausible-new-risk", "return fabricated.call();"),     # fabricated citation
    ])
    assert res.facts == []
    assert [o.result for o in res.outcomes] == ["unconfirmable", "unconfirmable", "unlocatable"]


def test_novel_budget_is_separate_and_tighter():
    """Novel discoveries spend `max_novel`, not the taxonomy budget — the open invitation can
    neither crowd out known categories nor flood a reviewer."""
    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("missing-cache-invalidation", _SHIP, target="shipping-api", severity="high"),
        Proposal("another-new-risk", _SHIP, target="shipping-api", severity="low"),
        Proposal("data-loss-path", _SHIP, target="shipping-api", severity="high"),
    ], max_novel=1, max_candidates=None)
    by_cat = {o.proposal.category: o.result for o in res.outcomes}
    assert by_cat["missing-cache-invalidation"] == "routed"   # highest severity kept
    assert by_cat["another-new-risk"] == "capped"             # over the novel budget
    assert by_cat["data-loss-path"] == "routed"               # taxonomy budget untouched
    assert len(res.facts) == 2


def test_novel_gap_scaffolds_named_by_proposed_category_and_validates():
    from sre_kb.pipeline.gap_finder import scaffold_gap
    from sre_kb.validation.structural import validate_doc as _validate

    res = gap_finder.collect_from_proposals(_ctx(), [
        Proposal("missing-cache-invalidation", _SHIP, target="shipping-api", severity="high"),
    ])
    doc = scaffold_gap(res.facts[0], "checkout")
    assert _validate(doc) == []  # category=novel + proposedCategory pass the schema
    assert doc["metadata"]["name"] == "shipping-api-missing-cache-invalidation"
    assert doc["spec"]["proposedCategory"] == "missing-cache-invalidation"
    assert doc["status"] == "needs-review" and doc["spec"]["sourceTier"] == "llm"
    assert not doc.get("crossRefs")  # not necessarily resiliency — no ResiliencyPattern backlink
