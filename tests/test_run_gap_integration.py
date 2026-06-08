"""Gap-finder proposals wired into the main `run` pipeline.

When the target carries Copilot's `.sre/gap-proposals.json`, `sre-kb run` re-grounds the
proposals and surfaces the survivors as `ResiliencyGap` artifacts through the same validate/gate
path as everything else. Refutation-probe survivors land `needs-review`, `source_tier=llm`;
confirmation-probe survivors graduate to `source_tier=ast` and can verify. When no proposals file
exists, the integration is a complete no-op.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.validation import validate_kb_tree

GAP_FIXTURE = Path(__file__).parent / "fixtures" / "sample-gap-finder"
PLAIN_FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def _load(root: Path) -> dict[tuple[str, str], dict]:
    docs = {}
    for p in (root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        docs[(d["kind"], d["metadata"]["name"])] = d
    return docs


@pytest.fixture(scope="module")
def gap_result(tmp_path_factory):
    work = tmp_path_factory.mktemp("gapwork")
    return run_pipeline(str(GAP_FIXTURE), work_root=str(work), run_id="g", to_stage="validate")


def test_run_surfaces_grounded_gap_finder_results(gap_result):
    docs = _load(gap_result.root)
    gaps = {name: d for (kind, name), d in docs.items() if kind == "ResiliencyGap"}
    assert set(gaps) == {
        "payments-api-missing-timeout",
        "notifications-api-unguarded-critical-dependency",
        "ledger-repository-swallowed-failure",
        "emit-daily-reconciliation-undocumented-job",
    }, sorted(gaps)


def test_refutation_gap_is_tier_b_and_needs_review(gap_result):
    docs = _load(gap_result.root)
    gap = docs[("ResiliencyGap", "payments-api-missing-timeout")]
    assert gap["status"] == "needs-review"
    assert gap["spec"]["sourceTier"] == "llm"
    assert gap["spec"]["category"] == "missing-timeout"
    assert gap["confidence"] < 0.7
    assert (
        gap_result.root
        / "kb"
        / "needs-review"
        / "ResiliencyGap"
        / "payments-api-missing-timeout.yaml"
    ).exists()


def test_confirmation_gaps_graduate_to_tier_a_and_verify(gap_result):
    docs = _load(gap_result.root)
    for name, category in {
        "ledger-repository-swallowed-failure": "swallowed-failure",
        "emit-daily-reconciliation-undocumented-job": "undocumented-job",
    }.items():
        gap = docs[("ResiliencyGap", name)]
        assert gap["status"] == "verified"
        assert gap["spec"]["sourceTier"] == "ast"
        assert gap["spec"]["category"] == category
        assert gap["provenanceMode"] == "deterministic"
        assert "unverifiedAgainstLive" not in gap


def test_gap_facts_are_persisted_and_kb_still_validates(gap_result):
    facts = (gap_result.root / "facts" / "facts.jsonl").read_text()
    assert '"resiliency.gap"' in facts
    bad = [r for r in validate_kb_tree(gap_result.root / "kb") if not r.ok]
    assert not bad, [(r.path, r.errors) for r in bad]


def _obs_target(tmp_path: Path, *, extra_dep: str = "") -> Path:
    """A minimal target: a pom.xml (its artifactId line is the anchor) + a missing-tracing proposal."""
    import json

    target = tmp_path / "repo"
    (target / ".sre").mkdir(parents=True)
    deps = "<dependency>\n<artifactId>spring-boot-starter-web</artifactId>\n</dependency>\n"
    if extra_dep:
        deps += f"<dependency>\n<artifactId>{extra_dep}</artifactId>\n</dependency>\n"
    (target / "pom.xml").write_text(f"<project>\n<dependencies>\n{deps}</dependencies>\n</project>\n",
                                    encoding="utf-8")
    (target / ".sre" / "gap-proposals.json").write_text(json.dumps({"proposals": [{
        "category": "missing-tracing", "target": "orders-api", "severity": "medium",
        "anchor": "<artifactId>spring-boot-starter-web</artifactId>",
        "rationale": "web service with no distributed-tracing dependency",
    }]}), encoding="utf-8")
    return target


def test_observability_gap_routes_and_validates_end_to_end(tmp_path):
    """A missing-tracing proposal (no tracing dep) surfaces as a needs-review ResiliencyGap that
    validates against the schema's new enum, anchored on the config/build line."""
    res = run_pipeline(str(_obs_target(tmp_path)), work_root=str(tmp_path / "w"), run_id="obs",
                       to_stage="validate")
    gap = _load(res.root)[("ResiliencyGap", "orders-api-missing-tracing")]
    assert gap["status"] == "needs-review" and gap["spec"]["sourceTier"] == "llm"
    assert gap["spec"]["category"] == "missing-tracing"
    assert gap["evidence"][0]["path"] == "pom.xml"
    assert not [r for r in validate_kb_tree(res.root / "kb") if not r.ok]


def test_observability_gap_is_refuted_by_a_present_signal_end_to_end(tmp_path):
    """With a tracing dependency present, the engine refutes the gap against its own facts — no
    ResiliencyGap is produced (proves the orchestrator threads its fact set into the gap-finder)."""
    target = _obs_target(tmp_path, extra_dep="spring-cloud-starter-sleuth")
    res = run_pipeline(str(target), work_root=str(tmp_path / "w"), run_id="obs2", to_stage="validate")
    assert not [k for k in _load(res.root) if k[0] == "ResiliencyGap"]


def test_no_proposals_is_a_noop(tmp_path):
    res = run_pipeline(str(PLAIN_FIXTURE), work_root=str(tmp_path), run_id="p", to_stage="validate")
    docs = _load(res.root)
    assert not [k for k in docs if k[0] == "ResiliencyGap"]
    assert '"resiliency.gap"' not in (res.root / "facts" / "facts.jsonl").read_text()
