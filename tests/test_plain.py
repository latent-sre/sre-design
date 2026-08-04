"""Plain-English projections (3am mode): the fixed vocabulary, the flow narration, and the
hash-checked verbatim evidence excerpts — the non-developer's view of a runbook.

The load-bearing property is honesty: every sentence projects fields the KB already
validated (never an inference), unknown tokens degrade to sanitized raw values, and an
excerpt embeds ONLY while the cited bytes still hash to the artifact's excerptHash.
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import hash_excerpt
from sre_kb.render.copilot import runbook_markdown
from sre_kb.render.plain import (
    evidence_excerpt,
    failure_sentence,
    flow_plain_english,
    mode_phrase,
    runbook_excerpts,
    step_phrase,
    surfaced_phrase,
)

FLOW = {
    "kind": "Flow",
    "metadata": {"name": "create-order", "service": "order-service"},
    "spec": {
        "trigger": {"method": "POST", "path": "/api/v1/orders"},
        "steps": [
            {"id": "s1", "name": "call-reserve", "kind": "http-egress",
             "failureModes": [{"mode": "timeout", "surfacedAs": "http-503"}]},
            {"id": "s2", "name": "publish", "kind": "message-egress",
             "failureModes": [{"mode": "broker-unavailable",
                               "surfacedAs": "logged-and-swallowed", "dataLossRisk": True}]},
        ],
        "sinks": [{"type": "http", "target": "inventory"},
                  {"type": "kafka", "target": "order.created"}],
    },
}


def test_fixed_vocabulary_covers_the_engine_emitted_tokens():
    assert step_phrase("db-write") == "writes to the database"
    assert mode_phrase("circuit-open") == "the circuit breaker is open after repeated failures"
    assert "HTTP 503" in surfaced_phrase("http-503")
    assert "ignored" in surfaced_phrase("logged-and-swallowed")


def test_unknown_tokens_degrade_to_sanitized_raw_values():
    # A hand-authored artifact with novel tokens still narrates — sanitized, never invented.
    assert step_phrase("grpc-egress") == "runs step kind grpc-egress"
    assert mode_phrase("weird`mode\nx") == "weirdmode x"  # inline: backticks + newlines gone
    assert surfaced_phrase("grpc-14") == "surfaced as grpc-14"


def test_failure_sentence_names_data_loss():
    fm = {"mode": "broker-unavailable", "surfacedAs": "logged-and-swallowed", "dataLossRisk": True}
    s = failure_sentence(fm)
    assert "THE DATA IS LOST" in s and s.endswith(".")
    assert "DATA IS LOST" not in failure_sentence({"mode": "timeout", "surfacedAs": "http-503"})


def test_flow_narration_names_trigger_targets_and_failures():
    lines = flow_plain_english(FLOW)
    assert lines[0] == "1. A client sends `POST /api/v1/orders` to order-service."
    assert "calls another service (`inventory`)" in lines[1]
    assert "If the call takes too long (timeout)" in lines[1]
    assert "THE DATA IS LOST" in lines[2]


def test_flow_narration_survives_unpaired_sinks_without_mispairing():
    flow = {"metadata": {}, "spec": {"trigger": {}, "steps": FLOW["spec"]["steps"], "sinks": []}}
    lines = flow_plain_english(flow)
    assert lines[0] == "1. A trigger starts this flow in the service."
    assert "(`inventory`)" not in lines[1]  # no sink pairing -> no target name is guessed


def _cited(tmp_path: Path, text: str, start: int, end: int) -> tuple[dict, Path]:
    f = tmp_path / "src" / "A.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    lines = f.read_text(encoding="utf-8").splitlines(keepends=True)
    ev = {"path": "src/A.java", "lines": {"start": start, "end": end},
          "excerptHash": hash_excerpt(lines, start, end)}
    return ev, tmp_path


def test_excerpt_embeds_matching_bytes_verbatim(tmp_path):
    ev, root = _cited(tmp_path, "a\ncatch (Exception e) {\nlog.error(x);\n}\n", 2, 3)
    x = evidence_excerpt(ev, root)
    assert x["header"] == "src/A.java:2-3"
    assert x["code"] == "catch (Exception e) {\nlog.error(x);"
    assert x["lang"] == "java" and x["fence"] == "```"


def test_excerpt_refuses_drifted_bytes(tmp_path):
    ev, root = _cited(tmp_path, "a\nb\nc\n", 2, 2)
    (root / "src" / "A.java").write_text("a\nCHANGED\nc\n", encoding="utf-8")
    assert evidence_excerpt(ev, root) is None  # the file moved on — embedding would mis-cite


def test_excerpt_refuses_escapes_bounds_and_oversize(tmp_path):
    ev, root = _cited(tmp_path, "a\nb\n", 1, 1)
    assert evidence_excerpt({**ev, "path": "../outside"}, root) is None
    assert evidence_excerpt({**ev, "lines": {"start": 1, "end": 99}}, root) is None
    assert evidence_excerpt({**ev, "lines": {"start": 1, "end": 60}}, root) is None  # > cap
    assert evidence_excerpt({**ev, "lines": {"start": 0, "end": 1}}, root) is None


def test_excerpt_fence_outgrows_backticks_in_code(tmp_path):
    ev, root = _cited(tmp_path, 'x = "````"\n', 1, 1)
    x = evidence_excerpt(ev, root)
    assert x["fence"] == "`" * 5  # longer than the 4-run inside, so the block can't break out


def test_runbook_markdown_embeds_narration_and_excerpts(tmp_path):
    ev, root = _cited(tmp_path, "try {\n} catch (Exception e) { }\n", 2, 2)
    runbook = {
        "kind": "Runbook",
        "metadata": {"name": "create-order-dependency-failures"},
        "spec": {"trigger": {"alertRef": "a"}, "remediation": ["check things"],
                 "relatedFlow": "create-order"},
        "evidence": [ev, ev],  # duplicate citation renders once
    }
    md = runbook_markdown(runbook, FLOW, target_root=root)
    assert "## What this flow does (plain English)" in md
    assert "## The code this runbook points at" in md
    assert md.count("src/A.java:2-2") == 1
    assert "} catch (Exception e) { }" in md
    # Without the target root the same runbook renders minus the excerpt section.
    md_bare = runbook_markdown(runbook, FLOW)
    assert "The code this runbook points at" not in md_bare
    assert "What this flow does (plain English)" in md_bare
    assert runbook_excerpts(runbook, None) == []
