"""HYBRID-PLAN §9.7 N5 — the advisory, Tier-B findings narrative. The engine emits a closed-world
brief and grounds the LLM's returned prose against the digest: a narrative may reference only artifacts
the run actually contains, so a hallucinated risk can't masquerade as a finding. The narrative never
gates and never auto-verifies."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sre_kb.cli import app
from sre_kb.pipeline import run as run_pipeline
from sre_kb.render import load_kb
from sre_kb.reporting import (
    collect_findings,
    narrative_brief,
    render_narrative,
    validate_narrative,
)
from sre_kb.reporting.narrative import allowed_refs

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"

# Two BlastRadius artifacts that each yield a finding, plus a Flow the narrative may reference.
_DOCS = [
    {"kind": "BlastRadius", "metadata": {"name": "order-repository"}, "status": "verified",
     "spec": {"node": {"name": "order-repository"}, "severityHint": "high",
              "dependencyCriticality": "critical", "impactedFlows": ["create-order"]},
     "evidence": [{"path": "X.java", "lines": {"start": 1, "end": 2}}]},
    {"kind": "Flow", "metadata": {"name": "create-order"}, "status": "verified"},
]


def _findings():
    return collect_findings(_DOCS)


# --- brief ----------------------------------------------------------------------------------------
def test_brief_is_a_closed_world_of_real_artifacts():
    brief = narrative_brief("order-service", "r1", _findings(), _DOCS)
    assert brief["summary"]["findings"] == 1 and brief["summary"]["high"] == 1
    assert "BlastRadius/order-repository" in brief["allowedRefs"]
    assert "Flow/create-order" in brief["allowedRefs"]
    assert brief["findings"][0]["artifact"] == "BlastRadius/order-repository"
    assert "do not invent" in brief["instruction"]


def test_allowed_refs_unions_artifacts_and_findings():
    refs = allowed_refs(_findings(), _DOCS)
    assert {"BlastRadius/order-repository", "Flow/create-order"} <= refs


# --- grounding ------------------------------------------------------------------------------------
def test_narrative_referencing_only_real_artifacts_is_grounded():
    text = ("The critical dependency `BlastRadius/order-repository` needs a circuit breaker; "
            "it degrades `Flow/create-order` on failure.")
    check = validate_narrative(text, _findings(), _DOCS)
    assert check.grounded
    assert "BlastRadius/order-repository" in check.cited_refs and check.unknown_refs == []


def test_narrative_inventing_an_artifact_is_flagged_ungrounded():
    text = "Biggest risk is BlastRadius/ghost-service falling over. Also see Flow/create-order."
    check = validate_narrative(text, _findings(), _DOCS)
    assert not check.grounded
    assert check.unknown_refs == ["BlastRadius/ghost-service"]  # the hallucination is named
    assert "Flow/create-order" in check.cited_refs              # the real ref still resolves


def test_ordinary_prose_with_a_slash_is_not_mistaken_for_a_citation():
    # "TCP/IP" (unknown Kind) and "client/server" (lowercase) must not be read as artifact refs.
    check = validate_narrative("Tune the client/server TCP/IP read timeout.", _findings(), _DOCS)
    assert check.grounded and check.unknown_refs == [] and check.cited_refs == []


# --- rendering ------------------------------------------------------------------------------------
def test_render_labels_advisory_and_surfaces_ungrounded_refs():
    check = validate_narrative("Risk: BlastRadius/ghost is high.", _findings(), _DOCS)
    out = render_narrative("order-service", "Risk: BlastRadius/ghost is high.", check)
    assert "advisory · needs-review · source: LLM" in out
    assert "Tier-B advisory" in out
    assert "Ungrounded references" in out and "`BlastRadius/ghost`" in out


# --- end to end against a real run ----------------------------------------------------------------
def test_narrative_grounds_against_a_real_run(tmp_path):
    r = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="nar", to_stage="validate")
    docs = load_kb(r.root)
    found = collect_findings(docs)
    brief = narrative_brief("order-service", "nar", found, docs)
    assert brief["allowedRefs"]  # the run has real artifacts to reference
    ref = brief["allowedRefs"][0]
    grounded = validate_narrative(f"Top concern: {ref} warrants review.", found, docs)
    assert grounded.grounded and ref in grounded.cited_refs
    bad = validate_narrative("Concern: BlastRadius/does-not-exist is severe.", found, docs)
    assert not bad.grounded and "BlastRadius/does-not-exist" in bad.unknown_refs


# --- CLI round trip -------------------------------------------------------------------------------
def test_cli_emits_brief_then_validates_a_narrative(tmp_path):
    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="cli", to_stage="validate")
    runner = CliRunner()

    brief = runner.invoke(app, ["findings-narrative", "--run", "cli", "--work-root", str(tmp_path)])
    assert brief.exit_code == 0 and '"allowedRefs"' in brief.stdout

    # A narrative citing an artifact the run doesn't contain fails (BlastRadius is a real kind here).
    bad = tmp_path / "bad.md"
    bad.write_text("The risk is BlastRadius/not-a-real-artifact.", encoding="utf-8")
    res = runner.invoke(app, ["findings-narrative", "--run", "cli", "--narrative", str(bad),
                              "--work-root", str(tmp_path)])
    assert res.exit_code == 1  # ungrounded narrative fails
    assert "Ungrounded references" in res.stdout
