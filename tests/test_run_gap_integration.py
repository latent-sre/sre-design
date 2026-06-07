"""Tier-B gap-finder wired into the main `run` pipeline (HYBRID-PLAN §9.3, priority 1).

When the target carries Copilot's `.sre/gap-proposals.json`, `sre-kb run` must re-ground the
proposals and surface the survivors as `ResiliencyGap` artifacts through the SAME validate/gate
path as everything else — landing `needs-review`, `source_tier=llm`, never auto-verified. When no
proposals file exists, the integration is a complete no-op.
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


def test_run_surfaces_only_the_confirmed_gap(gap_result):
    docs = _load(gap_result.root)
    gaps = {name: d for (kind, name), d in docs.items() if kind == "ResiliencyGap"}
    # The fixture plants 3 proposals: 1 real gap, 1 refuted (@TimeLimiter present), 1 hallucinated.
    # Only the real one survives re-grounding and reaches the KB.
    assert set(gaps) == {"payments-api-missing-timeout"}, sorted(gaps)


def test_surfaced_gap_is_tier_b_and_never_verified(gap_result):
    docs = _load(gap_result.root)
    gap = docs[("ResiliencyGap", "payments-api-missing-timeout")]
    assert gap["status"] == "needs-review"          # contract: never auto-verify
    assert gap["spec"]["sourceTier"] == "llm"        # Tier-B
    assert gap["spec"]["category"] == "missing-timeout"
    assert gap["confidence"] < 0.7                    # below the verified floor
    # It lives under the needs-review tree, not verified.
    assert (gap_result.root / "kb" / "needs-review" / "ResiliencyGap"
            / "payments-api-missing-timeout.yaml").exists()


def test_gap_facts_are_persisted_and_kb_still_validates(gap_result):
    facts = (gap_result.root / "facts" / "facts.jsonl").read_text()
    assert '"resiliency.gap"' in facts               # merged into the fact stream
    bad = [r for r in validate_kb_tree(gap_result.root / "kb") if not r.ok]
    assert not bad, [(r.path, r.errors) for r in bad]


def test_no_proposals_is_a_noop(tmp_path):
    # The plain fixture has no .sre/gap-proposals.json — run must produce zero ResiliencyGap docs.
    res = run_pipeline(str(PLAIN_FIXTURE), work_root=str(tmp_path), run_id="p", to_stage="validate")
    docs = _load(res.root)
    assert not [k for k in docs if k[0] == "ResiliencyGap"]
    assert '"resiliency.gap"' not in (res.root / "facts" / "facts.jsonl").read_text()
