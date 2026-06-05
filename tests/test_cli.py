"""CLI smoke tests: registry introspection works, and `validate-kb` passes on a good
tree and fails (non-zero) on a bad one — proving the validation gate is wired."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sre_kb.cli import app

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_schema_list_includes_p1_kinds() -> None:
    result = runner.invoke(app, ["schema", "list"])
    assert result.exit_code == 0
    assert "Flow" in result.stdout
    assert "Runbook" in result.stdout
    assert "BlastRadius" in result.stdout


def test_validate_kb_passes_on_good_tree() -> None:
    result = runner.invoke(app, ["validate-kb", str(FIXTURES / "kb-good")])
    assert result.exit_code == 0, result.stdout
    assert "0 failed" in result.stdout


def test_validate_kb_fails_on_bad_tree() -> None:
    result = runner.invoke(app, ["validate-kb", str(FIXTURES / "kb-bad")])
    assert result.exit_code == 1
    assert "FAIL" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "sre-kb" in result.stdout
