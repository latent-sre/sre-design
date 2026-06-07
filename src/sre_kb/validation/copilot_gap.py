"""Validation harness for the real-Copilot gap-finder run.

The engine still does not call Copilot. This module measures the JSON that Copilot already wrote
against a target-specific truth set, then reports both raw LLM proposal quality and post-grounding
quality after the deterministic gap-finder has accepted/refuted/routed the proposals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sre_kb.collectors.llm.gap_finder import Outcome
from sre_kb.pipeline.gap_finder import run_gap_finder

GapKey = tuple[str, str]


def _key(category: str | None, target: str | None) -> GapKey | None:
    cat = (category or "").strip().lower()
    tgt = (target or "").strip().lower()
    if not cat:
        return None
    return cat, tgt


def _proposal_key(outcome: Outcome) -> GapKey:
    return (
        outcome.proposal.category.strip().lower(),
        (outcome.proposal.target or "").strip().lower(),
    )


def _load_key_set(items: list[dict[str, Any]]) -> set[GapKey]:
    keys: set[GapKey] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = _key(item.get("category") or item.get("pattern"), item.get("target"))
        if key:
            keys.add(key)
    return keys


@dataclass(frozen=True)
class GapTruth:
    expected: set[GapKey]
    controls: set[GapKey]


@dataclass(frozen=True)
class CopilotGapValidation:
    target: str
    proposals_path: str
    truth_path: str
    expected: set[GapKey]
    controls: set[GapKey]
    proposed: set[GapKey]
    grounded: set[GapKey]
    kept: set[GapKey]
    confirmed: set[GapKey]
    missed_expected: set[GapKey]
    false_positive_proposals: set[GapKey]
    false_positive_kept: set[GapKey]
    controls_proposed: set[GapKey]
    controls_kept: set[GapKey]
    outcomes: list[Outcome]
    by_status: dict[str, int]

    @property
    def proposal_recall(self) -> float:
        return len(self.proposed & self.expected) / len(self.expected)

    @property
    def kept_recall(self) -> float:
        return len(self.kept & self.expected) / len(self.expected)

    @property
    def proposal_precision(self) -> float | None:
        if not self.proposed:
            return None
        return len(self.proposed & self.expected) / len(self.proposed)

    @property
    def kept_precision(self) -> float | None:
        if not self.kept:
            return None
        return len(self.kept & self.expected) / len(self.kept)

    @property
    def grounded_rate(self) -> float | None:
        if not self.proposed:
            return None
        return len(self.grounded) / len(self.proposed)

    def passes(self, *, min_recall: float, min_kept_precision: float) -> bool:
        if self.kept_recall < min_recall:
            return False
        kept_precision = self.kept_precision
        return kept_precision is not None and kept_precision >= min_kept_precision

    def as_dict(self) -> dict[str, Any]:
        def keys(values: set[GapKey]) -> list[dict[str, str]]:
            return [
                {"category": category, "target": target}
                for category, target in sorted(values)
            ]

        return {
            "target": self.target,
            "proposalsPath": self.proposals_path,
            "truthPath": self.truth_path,
            "counts": {
                "expected": len(self.expected),
                "proposed": len(self.proposed),
                "grounded": len(self.grounded),
                "kept": len(self.kept),
                "confirmed": len(self.confirmed),
                "missedExpected": len(self.missed_expected),
                "falsePositiveProposals": len(self.false_positive_proposals),
                "falsePositiveKept": len(self.false_positive_kept),
            },
            "metrics": {
                "proposalRecall": self.proposal_recall,
                "keptRecall": self.kept_recall,
                "proposalPrecision": self.proposal_precision,
                "keptPrecision": self.kept_precision,
                "groundedRate": self.grounded_rate,
            },
            "expected": keys(self.expected),
            "controls": keys(self.controls),
            "missedExpected": keys(self.missed_expected),
            "falsePositiveProposals": keys(self.false_positive_proposals),
            "falsePositiveKept": keys(self.false_positive_kept),
            "controlsProposed": keys(self.controls_proposed),
            "controlsKept": keys(self.controls_kept),
            "byStatus": dict(sorted(self.by_status.items())),
            "outcomes": [
                {
                    "category": outcome.proposal.category,
                    "target": outcome.proposal.target,
                    "severity": outcome.proposal.severity,
                    "result": outcome.result,
                    "path": outcome.path,
                    "lines": list(outcome.lines) if outcome.lines else None,
                    "note": outcome.note,
                }
                for outcome in self.outcomes
            ],
        }


def load_gap_truth(path: str | Path) -> GapTruth:
    """Load the expected real gaps for a Copilot validation target.

    Format:
      {"expected": [{"category": "...", "target": "..."}],
       "controls": [{"category": "...", "target": "..."}]}

    A bare list is accepted as shorthand for {"expected": [...]}.
    """
    truth_path = Path(path)
    data = json.loads(truth_path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        expected_items = data
        control_items: list[dict[str, Any]] = []
    elif isinstance(data, dict):
        expected_items = data.get("expected") or []
        control_items = data.get("controls") or []
    else:
        expected_items, control_items = [], []
    expected = _load_key_set(expected_items)
    if not expected:
        raise ValueError(f"truth file has no expected gaps: {truth_path}")
    return GapTruth(expected=expected, controls=_load_key_set(control_items))


def validate_copilot_gap_run(
    target: str | Path,
    *,
    truth_path: str | Path,
    proposals_path: str | Path | None = None,
    service: str | None = None,
) -> CopilotGapValidation:
    """Measure a saved Copilot proposal file against the target's truth set."""
    target_path = Path(target)
    proposal_path = Path(proposals_path) if proposals_path else target_path / ".sre" / "gap-proposals.json"
    truth = load_gap_truth(truth_path)
    run = run_gap_finder(str(target_path), proposals_path=proposal_path, service=service)

    proposed = {_proposal_key(outcome) for outcome in run.result.outcomes}
    grounded = {_proposal_key(outcome) for outcome in run.result.outcomes if outcome.path}
    kept = {_proposal_key(outcome) for outcome in run.result.kept()}
    confirmed = {_proposal_key(outcome) for outcome in run.result.confirmed()}
    false_positive_proposals = proposed - truth.expected
    false_positive_kept = kept - truth.expected

    return CopilotGapValidation(
        target=str(target_path),
        proposals_path=str(proposal_path),
        truth_path=str(truth_path),
        expected=truth.expected,
        controls=truth.controls,
        proposed=proposed,
        grounded=grounded,
        kept=kept,
        confirmed=confirmed,
        missed_expected=truth.expected - kept,
        false_positive_proposals=false_positive_proposals,
        false_positive_kept=false_positive_kept,
        controls_proposed=false_positive_proposals & truth.controls,
        controls_kept=false_positive_kept & truth.controls,
        outcomes=run.result.outcomes,
        by_status=run.by_status,
    )
