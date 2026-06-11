"""Automated scan-worklist loop: drive every discover/confirm task through a stubbed
LLMProvider and land each output in the exact file the manual IDE exchange would have
written — automation changes the transport, never the trust boundary."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from sre_kb.pipeline import run as run_pipeline
from sre_kb.pipeline.worklist_run import (
    extract_json_object,
    parse_confirm_reply,
    run_scan_worklist,
)
from sre_kb.workspace import RunLayout

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


class StubProvider:
    """A programmatic provider standing in for the oracle CLI; answers by prompt content."""

    id = "stub"
    interactive = False

    def __init__(self, answer):
        self._answer = answer
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._answer(prompt)

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)


# --------------------------------------------------------------------- reply parsing

def test_parse_confirm_reply_affirm_and_anything_unparseable_is_affirm():
    # affirm is the no-op: the engine's claim stands — the safe default for every shape of reply
    assert parse_confirm_reply("affirm") == ("affirm", "")
    assert parse_confirm_reply("Affirmed — genuinely absent")[0] == "affirm"
    assert parse_confirm_reply("")[0] == "affirm"
    assert parse_confirm_reply("I would dispute this if I could")[0] == "affirm"
    assert parse_confirm_reply("not disputing")[0] == "affirm"


def test_parse_confirm_reply_dispute_extracts_fenced_anchor():
    verdict, anchor = parse_confirm_reply(
        "dispute — present here:\n```java\n.timeout(Duration.ofSeconds(2))\n```"
    )
    assert verdict == "dispute"
    assert anchor == ".timeout(Duration.ofSeconds(2))"


def test_parse_confirm_reply_dispute_single_line_and_markdown():
    assert parse_confirm_reply("dispute: resilience4j.timelimiter.instances.x")[1] == (
        "resilience4j.timelimiter.instances.x"
    )
    verdict, anchor = parse_confirm_reply("**Disputed** — see below\n`enabled: false`")
    assert verdict == "dispute" and anchor == "enabled: false"


def test_parse_confirm_reply_empty_anchor_dispute_is_still_safe():
    # a bare dispute carries no anchor — downstream re-grounding leaves the claim standing
    assert parse_confirm_reply("dispute") == ("dispute", "")


# --------------------------------------------------------------------- JSON extraction

def test_extract_json_object_direct_fenced_and_embedded():
    doc = {"proposals": [{"category": "missing-timeout", "anchor": "x"}]}
    assert extract_json_object(json.dumps(doc)) == doc
    assert extract_json_object(f"Here you go:\n```json\n{json.dumps(doc)}\n```\ndone") == doc
    assert extract_json_object(f"prose before {json.dumps(doc)} prose after") == doc
    assert extract_json_object("[]") == []


def test_extract_json_object_never_invents():
    assert extract_json_object("") is None
    assert extract_json_object("no gaps found, all good") is None
    assert extract_json_object('{"proposals": [broken') is None


# --------------------------------------------------------------------- the runner

def _automated_oracle(prompt: str) -> str:
    if "Gap-finder context" in prompt:
        return json.dumps({"proposals": [
            {"category": "missing-timeout", "target": "inventory-service", "severity": "high",
             "anchor": "not actually in the fixture", "rationale": "stub"},
        ]})
    if "-draft context" in prompt or "Contract-review context" in prompt:
        return '{"proposals": []}'  # alert/runbook/architecture drafts + contract review
    if "deployment-review context" in prompt:
        return '{"proposals": []}'  # the stub finds nothing review-worthy
    if "Diagram-narration context" in prompt:
        return json.dumps({"narrations": [
            {"diagram": "create-order", "text": "Shows the order flow."}]})
    if "Coverage-discovery context" in prompt:
        return '{"areas": []}'  # the stub finds no new areas
    if "allowedRefs" in prompt:  # the narrative brief is a JSON document
        return "No significant risks beyond the digest."
    if "Affirm" in prompt or "affirm" in prompt:
        return "affirm"
    return "supported: fine"


def test_runner_writes_every_output_where_the_manual_loop_would(tmp_path):
    target = tmp_path / "target"
    shutil.copytree(FIXTURE, target)
    run_pipeline(str(target), work_root=str(tmp_path / "work"), run_id="wr", to_stage="validate")
    layout = RunLayout(tmp_path / "work", "wr")
    worklist = json.loads((layout.root / "scan-worklist.json").read_text())
    assert worklist["tasks"], "fixture run should produce LLM work"

    provider = StubProvider(_automated_oracle)
    summaries = run_scan_worklist(layout, worklist, provider, target=target)

    by_task = {s["task"]: s for s in summaries}
    assert set(by_task) == {t["id"] for t in worklist["tasks"]}
    assert all(s["status"] == "written" for s in summaries), summaries
    assert all(s["ingest"] for s in summaries)
    if "discover-gaps" in by_task:
        proposals = json.loads((target / ".sre" / "gap-proposals.json").read_text())
        assert proposals["proposals"][0]["category"] == "missing-timeout"
    if "confirm-challenge" in by_task:
        verdicts = json.loads((layout.root / "challenge" / "verdicts.json").read_text())
        assert verdicts["schema"] == "challenge.verdicts/v1" and verdicts["oracle"] == "stub"
    if "confirm-boundaries" in by_task:
        verdicts = json.loads((layout.root / "confirm" / "verdicts.json").read_text())
        assert verdicts["schema"] == "confirm.verdicts/v1"
        assert all(v["verdict"] == "affirm" for v in verdicts["verdicts"])
    if "draft-alerts" in by_task:
        assert json.loads((target / ".sre" / "alert-proposals.json").read_text()) == {"proposals": []}
    if "draft-runbooks" in by_task:
        assert json.loads((target / ".sre" / "runbook-proposals.json").read_text()) == {"proposals": []}
    if "findings-narrative" in by_task:
        text = (target / ".sre" / "findings-narrative.md").read_text()
        assert "No significant risks" in text
    if "review-pcf" in by_task:
        assert json.loads((target / ".sre" / "pcf-review-proposals.json").read_text()) == {"proposals": []}
    if "narrate-diagrams" in by_task:
        narrations = json.loads((target / ".sre" / "diagram-narrations.json").read_text())
        assert narrations["narrations"][0]["diagram"] == "create-order"
    if "discover-areas" in by_task:
        assert json.loads((target / ".sre" / "area-proposals.json").read_text()) == {"areas": []}


def test_runner_defers_discover_on_unparseable_reply_never_fabricates(tmp_path):
    target = tmp_path / "target"
    shutil.copytree(FIXTURE, target)
    run_pipeline(str(target), work_root=str(tmp_path / "work"), run_id="wd", to_stage="validate")
    layout = RunLayout(tmp_path / "work", "wd")
    worklist = json.loads((layout.root / "scan-worklist.json").read_text())

    provider = StubProvider(lambda p: "I found nothing worth reporting."
                            if "Gap-finder context" in p else "affirm")
    summaries = run_scan_worklist(layout, worklist, provider, target=target)
    by_task = {s["task"]: s for s in summaries}
    assert by_task["discover-gaps"]["status"] == "deferred"
    assert not (target / ".sre" / "gap-proposals.json").exists()


def test_runner_omits_unanswered_boundary_calls(tmp_path):
    """A failed oracle call (empty reply) must not be recorded as a fake affirmation —
    the claim stands by omission."""
    (tmp_path / "wo" / "confirm").mkdir(parents=True)
    (tmp_path / "wo" / "confirm" / "boundary-calls.json").write_text(json.dumps({
        "schema": "confirm.worklist/v1", "runId": "wo",
        "items": [{"claimId": "a", "prompt": "Affirm or dispute A."},
                  {"claimId": "b", "prompt": "Affirm or dispute B."}],
    }))
    layout = RunLayout(tmp_path, "wo")
    worklist = {"tasks": [{"id": "confirm-boundaries", "ingest": "sre-kb confirm-apply --run wo"}]}
    provider = StubProvider(lambda p: "" if "A." in p else "affirm")
    run_scan_worklist(layout, worklist, provider, target=tmp_path)
    verdicts = json.loads((tmp_path / "wo" / "confirm" / "verdicts.json").read_text())
    assert [v["claimId"] for v in verdicts["verdicts"]] == ["b"]


def test_runner_defers_everything_on_an_interactive_provider(tmp_path):
    from sre_kb.llm.provider import CopilotFileProvider

    layout = RunLayout(tmp_path, "wi")
    worklist = {"tasks": [{"id": "discover-gaps", "ingest": "x"},
                          {"id": "confirm-challenge", "ingest": "y"}]}
    summaries = run_scan_worklist(layout, worklist, CopilotFileProvider(), target=tmp_path)
    assert all(s["status"] == "deferred" for s in summaries)


def test_runner_surfaces_unknown_tasks_instead_of_dropping(tmp_path):
    layout = RunLayout(tmp_path, "wu")
    provider = StubProvider(lambda p: "affirm")
    summaries = run_scan_worklist(
        layout, {"tasks": [{"id": "future-task", "ingest": "z"}]}, provider, target=tmp_path)
    assert summaries == [{"task": "future-task", "status": "deferred",
                          "note": "unknown task — left to the manual loop"}]


# --------------------------------------------------------------------- CLI

def test_cli_worklist_run_without_oracle_defers(tmp_path):
    from typer.testing import CliRunner

    from sre_kb.cli import app

    target = tmp_path / "target"
    shutil.copytree(FIXTURE, target)
    run_pipeline(str(target), work_root=str(tmp_path / "work"), run_id="cd", to_stage="validate")
    res = CliRunner().invoke(
        app, ["worklist-run", "--run", "cd", "--work-root", str(tmp_path / "work")],
        env={"SRE_KB_ORACLE": ""},
    )
    assert res.exit_code == 0
    assert "deferred to the manual loop" in res.stdout
    assert not (target / ".sre" / "gap-proposals.json").exists()


def test_cli_worklist_run_with_oracle_writes_outputs_and_prints_ingest(tmp_path):
    from typer.testing import CliRunner

    from sre_kb.cli import app

    target = tmp_path / "target"
    shutil.copytree(FIXTURE, target)
    run_pipeline(str(target), work_root=str(tmp_path / "work"), run_id="cw", to_stage="validate")
    # a tiny oracle answering by prompt content, invoked via this interpreter
    oracle = (
        f"{sys.executable} -c \"import sys;p=sys.stdin.read();"
        "print('{\\\"proposals\\\": []}' if ('Gap-finder' in p or '-draft context' in p or "
        "'Contract-review' in p) else 'affirm' if 'Affirm' in p else 'supported: ok')\""
    )
    res = CliRunner().invoke(
        app, ["worklist-run", "--run", "cw", "--oracle", oracle,
              "--work-root", str(tmp_path / "work"), "--target", str(target)],
    )
    assert res.exit_code == 0, res.stdout
    assert "[written]" in res.stdout and "ingest" in res.stdout
    assert json.loads((target / ".sre" / "gap-proposals.json").read_text()) == {"proposals": []}
    assert (tmp_path / "work" / "cw" / "challenge" / "verdicts.json").exists()
