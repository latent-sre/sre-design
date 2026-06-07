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


def test_no_proposals_is_a_noop(tmp_path):
    res = run_pipeline(str(PLAIN_FIXTURE), work_root=str(tmp_path), run_id="p", to_stage="validate")
    docs = _load(res.root)
    assert not [k for k in docs if k[0] == "ResiliencyGap"]
    assert '"resiliency.gap"' not in (res.root / "facts" / "facts.jsonl").read_text()
