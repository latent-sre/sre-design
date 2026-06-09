"""Phase 0 trust-tier plumbing: every piece of evidence carries a `source_tier`
(defaulting to the deterministic "ast" tier), the collector protocol admits both
collector shapes, and the validation report surfaces each artifact's tier. These are
pure-plumbing guarantees — no artifact's status/confidence/content changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sre_kb.collectors.base import CollectorProtocol, ScanContext
from sre_kb.models.envelope import Artifact, Evidence, Lines, Metadata
from sre_kb.pipeline import run as run_pipeline
from sre_kb.tiers import artifact_tier, tier_label
from sre_kb.validation import validate_doc

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
_HASH = "sha256:" + "0" * 64


def _evidence(source_tier: str | None = None) -> Evidence:
    kw = {} if source_tier is None else {"source_tier": source_tier}
    return Evidence(
        repo="r", commit="0" * 40, path="p.java",
        lines=Lines(start=1, end=1), excerptHash=_HASH, detector="d", **kw,
    )


def test_evidence_default_source_tier_is_ast() -> None:
    assert _evidence().source_tier == "ast"


def test_scan_context_stamps_ast_by_default_and_llm_on_request() -> None:
    ctx = ScanContext(root=FIXTURE, repo="file://sample")
    assert ctx.evidence("manifest.yml", 1, 1, "test").source_tier == "ast"
    assert ctx.evidence("manifest.yml", 1, 1, "test", source_tier="llm").source_tier == "llm"


def test_collector_protocol_accepts_both_shapes() -> None:
    """A file-collector (collect(ctx)) and a deriver (collect(ctx, fs)) both satisfy it."""
    from sre_kb.collectors.common import manifest_pcf  # collect(ctx)
    from sre_kb.collectors.java_spring import flow_builder  # collect(ctx, fs)

    assert isinstance(manifest_pcf.collect, CollectorProtocol)
    assert isinstance(flow_builder.collect, CollectorProtocol)


@pytest.mark.parametrize("tier", ["ast", "llm"])
def test_source_tier_serializes_and_still_validates(tier: str) -> None:
    """Both tiers serialize into evidence and the artifact still passes the envelope schema —
    keeping the pydantic model and the JSON Schema in lock-step."""
    doc = Artifact(
        kind="Flow", metadata=Metadata(name="probe"), spec={}, status="needs-review",
        evidence=[_evidence(tier)],
    ).to_doc()
    assert doc["evidence"][0]["source_tier"] == tier
    assert not any("source_tier" in e for e in validate_doc(doc))


def test_schema_rejects_unknown_tier() -> None:
    """The model is permissive (str) but the schema enum confines tiers to ast|llm."""
    doc = Artifact(
        kind="Flow", metadata=Metadata(name="probe"), spec={}, status="needs-review",
        evidence=[_evidence("bogus")],
    ).to_doc()
    assert any("source_tier" in e or "bogus" in e for e in validate_doc(doc))


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict:
    work = tmp_path_factory.mktemp("work")
    result = run_pipeline(str(FIXTURE), work_root=str(work), run_id="tiers", to_stage="validate")
    return json.loads(result.report_path.read_text())


def test_report_exposes_tier_on_every_artifact(report: dict) -> None:
    assert report["records"], "expected the fixture to produce artifacts"
    # The deterministic AST pipeline produces only Tier-A evidence.
    assert all(rec["tier"] == "ast" for rec in report["records"])


def test_report_has_by_tier_rollup(report: dict) -> None:
    assert report["by_tier"] == {"ast": report["docs"]}


# --- §7.2 tier-aware guardrails + §7.5 surface the tier ---------------------------------


def test_artifact_tier_rolls_up_from_evidence() -> None:
    assert artifact_tier({}) == "ast"                                    # no evidence -> ast
    assert artifact_tier({"evidence": [{"source_tier": "ast"}]}) == "ast"
    # a single Tier-B citation taints the whole artifact (conservative roll-up)
    assert artifact_tier({"evidence": [{"source_tier": "ast"}, {"source_tier": "llm"}]}) == "llm"


def test_tier_label() -> None:
    assert tier_label("ast") == "AST-grounded"
    assert tier_label("llm") == "LLM-proposed"


def _cb_doc(name: str, source_tier: str) -> dict:
    return {"kind": "ResiliencyPattern", "metadata": {"name": name},
            "spec": {"type": "circuit-breaker", "targetSymbol": "Svc#call"},
            "evidence": [{"source_tier": source_tier}]}


def test_tier_b_finding_is_advisory_not_a_hard_guardrail() -> None:
    """The blast radius of an LLM mistake must never be a hard editor rule (§7.2)."""
    from sre_kb.render.copilot import advisory_notes, copilot_instructions, reliability_guardrails

    ast_doc, llm_doc = _cb_doc("a", "ast"), _cb_doc("b", "llm")
    assert reliability_guardrails([ast_doc]) and not advisory_notes([ast_doc])   # Tier-A -> hard
    assert advisory_notes([llm_doc]) and not reliability_guardrails([llm_doc])   # Tier-B -> advisory

    ci = copilot_instructions("svc", [llm_doc])
    assert "Advisory (LLM-proposed, unverified)" in ci
    hard = ci.split("## Reliability guardrails")[1].split("## Advisory")[0]
    assert "Svc#call" not in hard               # the Tier-B claim is not a hard rule


def test_findings_surface_tier() -> None:
    from sre_kb.reporting import collect_findings, render_md, render_text

    br = {"kind": "BlastRadius", "metadata": {"name": "kafka"},
          "spec": {"node": {"name": "kafka", "type": "broker"}, "severityHint": "high",
                   "stateful": {"dataLossRisk": True}, "impactedFlows": ["f"]},
          "evidence": [{"source_tier": "llm"}]}
    found = collect_findings([br])
    assert found and found[0]["tier"] == "llm"
    assert "LLM-proposed" in render_text("s", "r", found, [br])
    assert "LLM-proposed" in render_md("s", "r", found, [br])


def test_review_md_surfaces_tier() -> None:
    from sre_kb.publish.pr_builder import _review_md

    report = {"by_status": {"needs-review": 1}, "by_tier": {"llm": 1},
              "records": [{"artifact": "BlastRadius/x", "status": "needs-review", "tier": "llm"}]}
    md = _review_md([{}], report)
    assert "LLM-proposed 1" in md               # by_tier summary line
    assert "[LLM-proposed]" in md               # per-item tier tag


# --- §7.1 tier-conflict detector -------------------------------------------------------


def _fact(ftype: str, attrs: dict, tier: str):
    from sre_kb.models.facts import Fact

    ev = Evidence(repo="r", commit="0" * 40, path="p.java", lines=Lines(start=1, end=1),
                  excerptHash="sha256:" + "0" * 64, detector="d", source_tier=tier)
    return Fact(type=ftype, attrs=attrs, evidence=ev)


def test_tier_conflict_detects_disagreement() -> None:
    from sre_kb.reporting.findings import detect_tier_conflicts

    # Tier-A found a circuit breaker; Tier-B's gap-finder flags the same target as unguarded.
    facts = [_fact("resiliency.circuitbreaker", {"targetSymbol": "Inv#call"}, "ast"),
             _fact("gap.circuit-breaker", {"target": "Inv#call"}, "llm")]
    conflicts = detect_tier_conflicts(facts)
    assert len(conflicts) == 1
    assert conflicts[0]["concern"] == "circuit-breaker" and conflicts[0]["target"] == "Inv#call"
    assert conflicts[0]["astPresent"] and not conflicts[0]["llmPresent"]


def test_tier_conflict_silent_on_agreement_or_single_tier() -> None:
    from sre_kb.reporting.findings import detect_tier_conflicts

    agree = [_fact("resiliency.circuitbreaker", {"targetSymbol": "X"}, "ast"),
             _fact("resiliency.circuitbreaker", {"targetSymbol": "X"}, "llm")]
    assert detect_tier_conflicts(agree) == []                       # both assert present
    assert detect_tier_conflicts(agree[:1]) == []                   # only Tier-A -> no conflict


def test_report_has_no_tier_conflicts_on_ast_only(report: dict) -> None:
    assert report["tierConflicts"] == []   # no Tier-B producer yet -> nothing to conflict


def test_tier_conflict_fires_on_the_real_gap_finder_fact_shape() -> None:
    """The Phase-4 gap-finder emits `resiliency.gap` (category attrs), not the pre-Phase-4
    `gap.<concern>` shape — the detector was dead against every real run until it read it."""
    from sre_kb.reporting.findings import detect_tier_conflicts

    facts = [
        _fact("resiliency.circuitbreaker", {"targetSymbol": "payments-api"}, "ast"),
        _fact("resiliency.gap",
              {"category": "unguarded-critical-dependency", "target": "payments-api",
               "severity": "high", "rederivation": "confirmed"}, "llm"),
    ]
    conflicts = detect_tier_conflicts(facts)
    assert len(conflicts) == 1
    assert conflicts[0]["concern"] == "circuit-breaker"
    assert conflicts[0]["astPresent"] and not conflicts[0]["llmPresent"]
    # a non-overlapping category (missing-timeout has no Tier-A presence fact) stays silent
    quiet = [_fact("resiliency.gap", {"category": "missing-timeout", "target": "x"}, "llm")]
    assert detect_tier_conflicts(quiet) == []
