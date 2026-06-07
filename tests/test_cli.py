"""CLI smoke tests: registry introspection works, and `validate-kb` passes on a good
tree and fails (non-zero) on a bad one — proving the validation gate is wired."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from typer.testing import CliRunner

from sre_kb.cli import app
from sre_kb.config import schemas_dir
from sre_kb.models.envelope import Artifact, Evidence, Lines, Metadata

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


def test_validate_kb_honors_custom_schema_dir(tmp_path: Path) -> None:
    # the default schema dir passes the good tree ...
    ok = runner.invoke(app, ["validate-kb", "--schema-dir", str(schemas_dir()), str(FIXTURES / "kb-good")])
    assert ok.exit_code == 0, ok.stdout
    assert "0 failed" in ok.stdout
    # ... and a *stricter* custom schema dir is actually used: the same good tree now fails, proving
    # --schema-dir is honored rather than silently ignored (a same-dir assertion can't catch that).
    custom = tmp_path / "schemas"
    shutil.copytree(schemas_dir(), custom)
    envelope = custom / "_envelope.schema.json"
    schema = json.loads(envelope.read_text())
    schema["required"] = sorted({*schema.get("required", []), "__definitely_absent__"})
    envelope.write_text(json.dumps(schema))
    strict = runner.invoke(app, ["validate-kb", "--schema-dir", str(custom), str(FIXTURES / "kb-good")])
    assert strict.exit_code == 1, strict.stdout


def test_validate_kb_fails_on_bad_tree() -> None:
    result = runner.invoke(app, ["validate-kb", str(FIXTURES / "kb-bad")])
    assert result.exit_code == 1
    assert "FAIL" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "sre-kb" in result.stdout


def test_findings_gates_on_critical(tmp_path: Path) -> None:
    run = tmp_path / "run"
    kb = run / "kb" / "verified" / "BlastRadius"
    kb.mkdir(parents=True)
    doc = Artifact(
        kind="BlastRadius",
        metadata=Metadata(name="shared-db"),
        spec={
            "node": {"name": "shared-db"},
            "severityHint": "critical",
            "stateful": {"dataLossRisk": True},
            "impactedFlows": ["checkout"],
        },
        evidence=[
            Evidence(
                repo="file://sample",
                commit="0000000000000000000000000000000000000000",
                path="src/App.java",
                lines=Lines(start=1, end=1),
                excerptHash="sha256:" + ("0" * 64),
                detector="test",
            )
        ],
        confidence=0.9,
        status="verified",
    ).to_doc()
    (kb / "shared-db.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")

    result = runner.invoke(app, ["findings", "--run", "run", "--work-root", str(tmp_path)])
    assert result.exit_code == 1
    assert "[CRITICAL]" in result.stdout
