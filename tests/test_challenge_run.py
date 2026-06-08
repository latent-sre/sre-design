"""Live challenge loop: drive the worklist through a (stubbed) external oracle and feed
the result straight into challenge-apply. The oracle is a pluggable subprocess seam — the
engine itself still embeds no LLM."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sre_kb.pipeline import run as run_pipeline
from sre_kb.pipeline.challenge_apply import apply_verdicts
from sre_kb.pipeline.challenge_run import SubprocessOracle, run_worklist
from sre_kb.validation.challenge import parse_verdict_reply as parse_reply
from sre_kb.workspace import RunLayout

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
RUNBOOK = "Runbook/order-created-publish-failures"


def test_parse_reply_is_conservative():
    assert parse_reply("supported — breaker present at X.java:10") == (
        "supported",
        "supported — breaker present at X.java:10",
    )
    assert parse_reply("unsupported, no guard")[0] == "unsupported"
    assert parse_reply("CONTRADICTED: step deletes data")[0] == "contradicted"
    assert parse_reply("**Unsupported** — no evidence")[0] == "unsupported"  # markdown prefix
    # anything unreadable defers to a human — never a false pass
    assert parse_reply("")[0] == "indeterminate"
    assert parse_reply("I'm not sure about this one")[0] == "indeterminate"


def test_parse_reply_never_false_passes_on_negation():
    """Regression: a plain substring/regex search reads 'supported' out of these rejections.
    The shared parser must anchor on the first token, so a negating reply defers (safe),
    never silently passes the artifact through the downgrade-only gate."""
    for reply in ("not supported by the evidence", "un-supported", "cannot be supported",
                  "this is not supported"):
        assert parse_reply(reply)[0] == "indeterminate", reply


def test_run_worklist_attaches_artifact_and_claim_and_is_apply_shaped():
    worklist = {
        "schema": "challenge.worklist/v1",
        "runId": "r",
        "items": [{"artifact": RUNBOOK, "claimId": "runbook/remediation-safe", "prompt": "..."}],
    }
    out = run_worklist(worklist, lambda _p: "contradicted: unsafe", oracle_id="stub")
    assert out["schema"] == "challenge.verdicts/v1"
    assert out["oracle"] == "stub"  # oracle recorded once at the document level
    v = out["verdicts"][0]
    # each verdict keeps the documented {artifact, claimId, verdict, reason} shape
    assert set(v) == {"artifact", "claimId", "verdict", "reason"}
    assert v["artifact"] == RUNBOOK and v["claimId"] == "runbook/remediation-safe"
    assert v["verdict"] == "contradicted"


def test_subprocess_oracle_feeds_prompt_on_stdin_not_argv():
    # `cat` echoes stdin: proves the prompt travels on stdin, never the command line.
    oracle = SubprocessOracle("cat")
    assert "supported" in oracle("supported: ok")
    assert oracle.id.startswith("subprocess:")


def test_subprocess_oracle_missing_command_defers_not_crashes():
    assert parse_reply(SubprocessOracle("definitely-not-a-real-binary-xyz")("p"))[0] == "indeterminate"


def test_end_to_end_live_loop_downgrades_via_apply(tmp_path):
    """worklist -> stub oracle -> verdicts -> challenge-apply: a contradicted verdict
    rejects the runbook, proving the live path lands on the same monotonic gate."""
    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="lr", to_stage="validate")
    layout = RunLayout(Path(str(tmp_path)), "lr")
    worklist = json.loads((layout.root / "challenge" / "worklist.json").read_text())

    # a stub oracle standing in for the Copilot CLI: flags the runbook, passes the alert
    def stub(prompt: str) -> str:
        return "contradicted: step removes data without a guard" if "Runbook" in prompt else "supported: fine"

    verdicts = run_worklist(worklist, stub, oracle_id="stub")
    summary = {s["artifact"]: s for s in apply_verdicts(layout, verdicts)}
    assert summary[RUNBOOK]["new"] == "rejected"
    assert (layout.root / "reports" / "rejected" / "Runbook" / "order-created-publish-failures.yaml").exists()


def test_oracle_cannot_promote_only_downgrade(tmp_path):
    """Even if the oracle says 'supported' for everything, nothing is promoted: the
    worklist items start at needs-review and the gate is downgrade-only."""
    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="lp", to_stage="validate")
    layout = RunLayout(Path(str(tmp_path)), "lp")
    worklist = json.loads((layout.root / "challenge" / "worklist.json").read_text())
    verdicts = run_worklist(worklist, lambda _p: "supported: looks good", oracle_id="stub")
    for s in apply_verdicts(layout, verdicts):
        assert s["new"] == s["old"]  # no promotion, ever


def test_cli_challenge_run_without_oracle_defers(tmp_path):
    from typer.testing import CliRunner

    from sre_kb.cli import app

    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="cd", to_stage="validate")
    # ensure no inherited env oracle leaks into the test
    res = CliRunner().invoke(
        app, ["challenge-run", "--run", "cd", "--work-root", str(tmp_path)], env={"SRE_KB_ORACLE": ""}
    )
    assert res.exit_code == 0
    assert "deferred" in res.stdout
    assert not (Path(str(tmp_path)) / "cd" / "challenge" / "verdicts.json").exists()


def test_cli_challenge_run_with_oracle_writes_verdicts(tmp_path):
    from typer.testing import CliRunner

    from sre_kb.cli import app

    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="cw", to_stage="validate")
    # a tiny python oracle that always contradicts, invoked via this interpreter
    oracle = f"{sys.executable} -c \"import sys;sys.stdin.read();print('contradicted: stub')\""
    res = CliRunner().invoke(
        app, ["challenge-run", "--run", "cw", "--oracle", oracle, "--work-root", str(tmp_path)]
    )
    assert res.exit_code == 0, res.stdout
    vpath = Path(str(tmp_path)) / "cw" / "challenge" / "verdicts.json"
    data = json.loads(vpath.read_text())
    assert data["verdicts"] and all(v["verdict"] == "contradicted" for v in data["verdicts"])
