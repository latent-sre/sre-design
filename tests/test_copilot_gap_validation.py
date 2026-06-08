"""Real-Copilot validation harness for HYBRID-PLAN section 9.5 item 1.

The tests use a fixture proposal file, but the harness itself is the same one used after a human
runs Copilot in VS Code and saves the real `.sre/gap-proposals.json`.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from sre_kb.cli import app
from sre_kb.validation.copilot_gap import load_gap_truth, validate_copilot_gap_run

FIXTURE = Path(__file__).parent / "fixtures" / "sample-gap-finder"
TRUTH = FIXTURE / ".sre" / "gap-truth.json"
PROPOSALS = FIXTURE / ".sre" / "gap-proposals.json"


def test_truth_file_loads_expected_and_controls() -> None:
    truth = load_gap_truth(TRUTH)

    assert truth.expected == {
        ("missing-timeout", "payments-api"),
        ("swallowed-failure", "ledgerrepository"),
        ("undocumented-job", "emitdailyreconciliation"),
        ("unguarded-critical-dependency", "notifications-api"),
    }
    assert ("missing-timeout", "shipping-api") in truth.controls
    assert ("missing-timeout", "refunds-api") in truth.controls


def test_recall_is_none_when_no_expected_gaps() -> None:
    """With no expected gaps, recall is undefined — return None (like the precision properties)
    rather than ZeroDivisionError, and passes() conservatively fails."""
    from sre_kb.validation.copilot_gap import CopilotGapValidation

    v = CopilotGapValidation(
        target="t", proposals_path="p", truth_path="tr",
        expected=set(), controls=set(), proposed=set(), grounded=set(), kept=set(),
        confirmed=set(), missed_expected=set(), false_positive_proposals=set(),
        false_positive_kept=set(), controls_proposed=set(), controls_kept=set(),
        outcomes=[], by_status={},
    )
    assert v.proposal_recall is None and v.kept_recall is None
    assert v.passes(min_recall=1.0, min_kept_precision=1.0) is False


def test_copilot_gap_validation_reports_recall_precision_and_controls() -> None:
    report = validate_copilot_gap_run(FIXTURE, truth_path=TRUTH, proposals_path=PROPOSALS)

    assert report.proposal_recall == 1.0
    assert report.kept_recall == 1.0
    assert report.proposal_precision == 1.0
    assert report.kept_precision == 1.0
    assert report.grounded_rate == 1.0
    assert report.missed_expected == set()
    assert report.false_positive_kept == set()
    assert report.controls_proposed == set()
    assert report.controls_kept == set()


def test_copilot_gap_validate_cli_writes_report(tmp_path: Path) -> None:
    result_path = tmp_path / "real-copilot-validation.json"
    result = CliRunner().invoke(app, [
        "copilot-gap-validate",
        "--target",
        str(FIXTURE),
        "--truth",
        str(TRUTH),
        "--proposals",
        str(PROPOSALS),
        "--report",
        str(result_path),
    ])

    assert result.exit_code == 0, result.stdout
    assert "kept-recall=1.00" in result.stdout
    assert "kept-precision=1.00" in result.stdout
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["metrics"]["proposalRecall"] == 1.0
    assert payload["counts"]["falsePositiveKept"] == 0


def test_copilot_gap_validate_cli_fails_when_expected_gap_is_missed(tmp_path: Path) -> None:
    proposals = tmp_path / "gap-proposals.json"
    proposals.write_text(json.dumps({"proposals": []}), encoding="utf-8")

    result = CliRunner().invoke(app, [
        "copilot-gap-validate",
        "--target",
        str(FIXTURE),
        "--truth",
        str(TRUTH),
        "--proposals",
        str(proposals),
    ])

    assert result.exit_code == 1
    assert "kept-recall=0.00" in result.stdout
