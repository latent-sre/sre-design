"""The deterministic five-pass report stays useful and honest for non-developers."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from sre_kb.cli import app
from sre_kb.reporting import collect_findings
from sre_kb.reporting.human_report import PASS_NAMES, build_human_report, render_human_report

DOCS = [
    {"kind": "Flow", "metadata": {"name": "place-order"}, "status": "verified",
     "spec": {"trigger": {"method": "POST", "path": "/orders"},
              "steps": [{"name": "charge"}], "sinks": [{"target": "payments"}]}},
    {"kind": "ResiliencyPattern", "metadata": {"name": "payments-breaker"},
     "status": "verified", "spec": {}},
    {"kind": "ResiliencyGap", "metadata": {"name": "orders-missing-idempotency"},
     "status": "needs-review", "spec": {}},
    {"kind": "BlastRadius", "metadata": {"name": "payments"}, "status": "verified",
     "spec": {"node": {"name": "payments"}, "severityHint": "high",
              "dependencyCriticality": "critical", "impactedFlows": ["place-order"]}},
]


def test_report_has_exactly_five_deepening_passes_and_traceable_claims():
    report = build_human_report("orders", "r1", DOCS, collect_findings(DOCS))
    assert [p["name"] for p in report["passes"]] == list(PASS_NAMES)
    assert [p["number"] for p in report["passes"]] == [1, 2, 3, 4, 5]
    assert "POST /orders" in report["passes"][1]["details"][0]
    assert "payments" in report["passes"][1]["details"][0]
    assert "1 resilience protection" in report["passes"][3]["answer"]
    assert "1 resilience gap" in report["passes"][3]["answer"]
    assert report["passes"][4]["evidence"] == ["BlastRadius/payments"]


def test_markdown_states_runtime_boundary_and_operator_checkpoint():
    text = render_human_report(build_human_report("orders", "r1", DOCS, []))
    assert text.count("## Pass ") == 5
    assert "no claim of current production health" in text
    assert "## Operator checkpoint" in text and "metrics, logs, traces" in text


def test_cli_renders_markdown_and_json(monkeypatch, tmp_path):
    monkeypatch.setattr("sre_kb.render.load_kb", lambda _: DOCS)
    args = ["human-report", "--run", "r1", "--work-root", str(tmp_path)]
    md = CliRunner().invoke(app, args)
    assert md.exit_code == 0 and md.stdout.count("## Pass ") == 5
    raw = CliRunner().invoke(app, [*args, "--format", "json"])
    assert raw.exit_code == 0 and len(json.loads(raw.stdout)["passes"]) == 5


def test_cli_can_scan_a_target_then_report_it(monkeypatch, tmp_path):
    calls = []

    def fake_run(target, **kwargs):
        calls.append((target, kwargs))

    monkeypatch.setattr("sre_kb.pipeline.run", fake_run)
    monkeypatch.setattr("sre_kb.render.load_kb", lambda _: DOCS)
    result = CliRunner().invoke(
        app, ["human-report", "--target", str(tmp_path), "--work-root", str(tmp_path / "work")]
    )
    assert result.exit_code == 0 and result.stdout.count("## Pass ") == 5
    assert calls[0][0] == str(tmp_path)
    assert calls[0][1]["to_stage"] == "validate"


def test_cli_requires_exactly_one_input(tmp_path):
    runner = CliRunner()
    neither = runner.invoke(app, ["human-report", "--work-root", str(tmp_path)])
    both = runner.invoke(app, ["human-report", "--run", "r1", "--target", str(tmp_path)])
    assert neither.exit_code != 0 and "exactly one" in neither.output
    assert both.exit_code != 0 and "exactly one" in both.output


def test_cli_rejects_unknown_format(tmp_path):
    result = CliRunner().invoke(
        app, ["human-report", "--run", "r1", "--work-root", str(tmp_path), "--format", "xml"]
    )
    assert result.exit_code != 0 and "must be md or json" in result.output
