"""The remaining automation surfaces: the one-command accuracy measurement
(`copilot-gap-validate --oracle`), KB-vs-target drift (`diff --from-kb --fail-on-drift`), and
LLM-drafted + engine-verified graduation drafts (`graduation-draft`)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from typer.testing import CliRunner

from sre_kb.cli import app
from sre_kb.graduation import GraduationTracker
from sre_kb.pipeline.graduation_draft import draft_candidates

FIXTURES = Path(__file__).parent / "fixtures"
SPRING = FIXTURES / "sample-spring-pcf"
GAP = FIXTURES / "sample-gap-finder"


# ------------------------------------------------------- copilot-gap-validate --oracle

def test_gap_validate_oracle_generates_then_measures(tmp_path):
    """With --oracle, the command is the whole SCOPE §9 measurement recipe: the engine builds the
    prompt, the provider answers, the proposals land, and the measurement runs on them."""
    target = tmp_path / "target"
    shutil.copytree(GAP, target)
    (target / ".sre" / "gap-proposals.json").unlink()  # measure the oracle's, not the archived ones
    oracle = (f"{sys.executable} -c \"import sys;sys.stdin.read();"
              "print('{\\\"proposals\\\": []}')\"")
    res = CliRunner().invoke(app, [
        "copilot-gap-validate", "--target", str(target), "--truth",
        str(target / ".sre" / "gap-truth.json"), "--oracle", oracle,
    ])
    assert "oracle proposals ->" in res.stdout
    assert json.loads((target / ".sre" / "gap-proposals.json").read_text()) == {"proposals": []}
    # empty proposals against a non-empty truth set: measured, and failing the default floors
    assert "kept-recall=0.00" in res.stdout
    assert res.exit_code == 1


def test_gap_validate_oracle_unparseable_reply_is_an_error(tmp_path):
    target = tmp_path / "target"
    shutil.copytree(GAP, target)
    oracle = f"{sys.executable} -c \"import sys;sys.stdin.read();print('no json here')\""
    res = CliRunner().invoke(app, [
        "copilot-gap-validate", "--target", str(target), "--truth",
        str(target / ".sre" / "gap-truth.json"), "--oracle", oracle,
    ])
    assert res.exit_code == 2
    assert "did not parse" in res.output


# ------------------------------------------------------- diff --from-kb (scheduled drift)

def test_diff_from_kb_clean_when_kb_matches_target(tmp_path):
    """A published KB diffed against the target it was scanned from is drift-free."""
    target = tmp_path / "target"
    shutil.copytree(SPRING, target)
    run = CliRunner().invoke(app, ["run", "--target", str(target),
                                   "--work-root", str(tmp_path / "w"), "--run", "base"])
    assert run.exit_code == 0, run.output
    res = CliRunner().invoke(app, [
        "diff", "--from-kb", str(tmp_path / "w" / "base" / "kb"), "--to", str(target),
        "--fail-on-drift", "--work-root", str(tmp_path / "w"),
    ])
    assert res.exit_code == 0, res.output
    assert "drift: +0 -0 ~0" in res.stdout


def test_diff_from_kb_fails_on_drift(tmp_path):
    """An artifact missing from the published KB shows up as drift — and gates."""
    target = tmp_path / "target"
    shutil.copytree(SPRING, target)
    CliRunner().invoke(app, ["run", "--target", str(target),
                             "--work-root", str(tmp_path / "w"), "--run", "base"])
    kb = tmp_path / "w" / "base" / "kb"
    next(kb.rglob("Flow/*.yaml")).unlink()  # the published KB is missing a flow the target has
    res = CliRunner().invoke(app, [
        "diff", "--from-kb", str(kb), "--to", str(target),
        "--fail-on-drift", "--work-root", str(tmp_path / "w"),
    ])
    assert res.exit_code == 1
    assert "+1" in res.stdout


def test_diff_requires_exactly_one_base(tmp_path):
    res = CliRunner().invoke(app, ["diff", "--to", str(SPRING)])
    assert res.exit_code == 2
    assert "exactly one of" in res.output


# ------------------------------------------------------- graduation-draft

class StubProvider:
    id = "stub"
    interactive = False

    def __init__(self, reply: str):
        self.reply = reply

    def __call__(self, prompt: str) -> str:
        return self.reply


def _ready_tracker(target: Path, anchors: list[str]) -> None:
    tracker = GraduationTracker.load(target)
    for i, anchor in enumerate(anchors + [None] * (5 - len(anchors))):
        tracker.confirm("missing-timeout", run=f"r{i}", anchor=anchor)
    tracker.save(target)


def test_graduation_draft_verifies_pattern_against_anchors(tmp_path):
    _ready_tracker(tmp_path, ["restTemplate.getForObject(url, X.class)",
                              "restTemplate.postForObject(url, b, Y.class)"])
    provider = StubProvider(json.dumps(
        {"pattern": r"restTemplate\.\w+ForObject\(", "rationale": "blocking client call"}))
    drafts = draft_candidates(tmp_path, provider, tmp_path / "out")
    assert len(drafts) == 1
    d = drafts[0]
    assert d.fires_on == 2 and "fires on all 2" in d.note
    text = d.path.read_text()
    assert "restTemplate" in text and "fires on all 2" in text
    assert "never auto-applied" in text.lower() or "auto-applied" in text


def test_graduation_draft_rejects_uncompilable_pattern(tmp_path):
    _ready_tracker(tmp_path, ["client.call(x)"])
    drafts = draft_candidates(tmp_path, StubProvider('{"pattern": "(unclosed"}'), tmp_path / "out")
    assert drafts[0].fires_on == 0
    assert "does not compile" in drafts[0].note
    assert drafts[0].path.exists()  # the audit trail is written either way


def test_graduation_draft_unparseable_reply_keeps_the_sketch(tmp_path):
    _ready_tracker(tmp_path, ["client.call(x)"])
    drafts = draft_candidates(tmp_path, StubProvider("I cannot help with that."), tmp_path / "out")
    assert drafts[0].pattern is None and "unparseable" in drafts[0].note
    assert "Deterministic sketch" in drafts[0].path.read_text()


def test_cli_graduation_draft_without_candidates_or_oracle(tmp_path):
    res = CliRunner().invoke(app, ["graduation-draft", "--target", str(tmp_path)],
                             env={"SRE_KB_ORACLE": ""})
    assert res.exit_code == 0 and "nothing to draft" in res.stdout
    _ready_tracker(tmp_path, ["x.call()"])
    res = CliRunner().invoke(app, ["graduation-draft", "--target", str(tmp_path)],
                             env={"SRE_KB_ORACLE": ""})
    assert res.exit_code == 0 and "nothing drafted" in res.stdout
