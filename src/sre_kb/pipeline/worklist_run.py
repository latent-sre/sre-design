"""Drive the unified scan worklist through a programmatic `LLMProvider` — the automated
counterpart of the manual IDE file exchange (`synth/worklist.py`).

The manual loop is "read scan-worklist.json, run each task in the IDE, save to the declared
paths". This module runs the same tasks through the configured provider and lands every output
in the **exact file the manual exchange would have written**, so the deterministic ingest gates
downstream (`sre-kb run` re-grounding proposals, `challenge-apply`, `confirm-apply`) are
identical — automation changes the transport, never the trust boundary. The engine still embeds
no model: the provider is operator-configured (`--oracle`, or a config `llm` block).

Reply parsing is conservative by construction, mirroring `parse_verdict_reply`:
  - discover: a reply that doesn't parse to a proposals JSON object defers the task to the
    manual loop — nothing is fabricated, and whatever does parse is re-grounded byte-by-byte
    by the gap-finder anyway (an anchor that doesn't locate dies at the door).
  - confirm: only a reply whose first token *is* `dispute` counts as one; anything else (an
    affirm, prose, an empty/failed call) leaves the engine's claim standing — a dispute can
    only ever be *confirmed* by the engine re-deriving it at the cited bytes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sre_kb.workspace import RunLayout

_FENCE_LINE = re.compile(r"^\s*```[\w-]*\s*$")


def parse_confirm_reply(raw: str) -> tuple[str, str]:
    """Map a free-text reply to a boundary-call verdict ``(verdict, anchor)``. Safe by
    construction: only a reply whose first token starts with ``dispute`` is a dispute; everything
    else — affirms, prose, negations, an empty reply from a failed call — is ``affirm`` (the
    engine's claim stands, the no-op). A dispute's anchor is the quoted remainder (code fences
    stripped); a wrong or empty anchor is harmless because `confirm-apply` only acts when the
    engine's own deterministic rule fires at the located bytes."""
    lines = (raw or "").strip().splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
    first = lines[idx].strip().lstrip("*_#>-•· \t") if lines else ""
    if not first.lower().startswith("dispute"):
        return "affirm", ""
    rest = [ln for ln in lines[idx + 1 :] if not _FENCE_LINE.match(ln)]
    anchor = "\n".join(rest).strip().strip("`").strip()
    if not anchor:  # single-line dispute: the anchor is whatever follows the verdict token
        anchor = first[len("dispute"):].lstrip("dD").lstrip(":—-, ").strip().strip("`").strip('"')
    return "dispute", anchor


def extract_json_object(raw: str):
    """Pull the proposals JSON out of a free-text reply: the whole reply, a fenced ```json block,
    or the outermost brace/bracket span. Returns the parsed object (dict or list) or None — never
    raises, never invents. A None defers the task to the manual loop."""
    text = (raw or "").strip()
    candidates = [text]
    candidates += re.findall(r"```(?:json)?\s*\n(.*?)```", text, flags=re.S)
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if 0 <= start < end:
            candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except ValueError:
            continue
        if isinstance(data, dict | list):
            return data
    return None


def _run_discover(layout: RunLayout, provider, target: Path) -> dict:
    """Build the gap-finder prompt from the run's own facts, ask the provider, and write the
    proposals where the manual loop would have (`<target>/.sre/gap-proposals.json`). Ingest is the
    next `sre-kb run --target`, which re-grounds every proposal exactly as a hand-written file."""
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.llm.gap_finder import PROPOSALS_REL
    from sre_kb.models.facts import FactSet
    from sre_kb.pipeline.confirm import load_facts_of
    from sre_kb.synth.gap_prompt import build_gap_context

    ctx = ScanContext(root=target, repo=f"file://{target.name}")
    fs = FactSet(load_facts_of(layout.facts / "facts.jsonl",
                               "resiliency.circuitbreaker", "resiliency.fallback"))
    data = extract_json_object(provider(build_gap_context(ctx, fs)))
    if data is None:
        return {"task": "discover-gaps", "status": "deferred",
                "note": "unparseable reply — task left to the manual loop"}
    return _write_proposals(target, PROPOSALS_REL, "discover-gaps", data)


def _run_challenge(layout: RunLayout, provider) -> dict:
    from sre_kb.pipeline.challenge_run import run_worklist

    wpath = layout.root / "challenge" / "worklist.json"
    worklist = json.loads(wpath.read_text(encoding="utf-8"))
    result = run_worklist(worklist, provider, oracle_id=provider.id)
    out = layout.root / "challenge" / "verdicts.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return {"task": "confirm-challenge", "status": "written", "output": str(out),
            "note": f"{len(result['verdicts'])} verdict(s)"}


def _run_confirm(layout: RunLayout, provider) -> dict:
    """Adjudicate each boundary call; an unanswered call (empty/failed reply parses to affirm) is
    omitted rather than recorded as a fake affirmation — the claim stands by omission."""
    from sre_kb.pipeline.confirm import VERDICTS_SCHEMA

    wpath = layout.root / "confirm" / "boundary-calls.json"
    worklist = json.loads(wpath.read_text(encoding="utf-8"))
    verdicts = []
    for item in worklist.get("items", []):
        reply = provider(item["prompt"])
        if not (reply or "").strip():
            continue
        verdict, anchor = parse_confirm_reply(reply)
        verdicts.append({"claimId": item["claimId"], "verdict": verdict, "anchor": anchor})
    out = layout.root / "confirm" / "verdicts.json"
    out.write_text(json.dumps({"schema": VERDICTS_SCHEMA, "runId": worklist.get("runId"),
                               "oracle": provider.id, "verdicts": verdicts}, indent=2),
                   encoding="utf-8")
    return {"task": "confirm-boundaries", "status": "written", "output": str(out),
            "note": f"{len(verdicts)} verdict(s)"}


def _write_proposals(target: Path, rel: str, task: str, data) -> dict:
    """Land a parsed proposals object where the manual loop would have written it."""
    out = target / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = data if isinstance(data, dict) else {"proposals": data}
    out.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    n = len(doc.get("proposals") or [])
    return {"task": task, "status": "written", "output": str(out), "note": f"{n} proposal(s)"}


def _run_draft_alerts(layout: RunLayout, provider, target: Path) -> dict:
    """Ask which alertable (error/warn) log lines warrant paging; the ingest
    (`sre-kb generate-alerts`) re-locates each anchor, refutes by level, and derives the query."""
    from sre_kb.collectors.base import ScanContext
    from sre_kb.pipeline.alerts_draft import _ALERTABLE_LEVELS, PROPOSALS_REL
    from sre_kb.pipeline.confirm import load_facts_of
    from sre_kb.synth.draft_prompts import build_alert_prompt

    ctx = ScanContext(root=target, repo=f"file://{target.name}")
    statements = [f for f in load_facts_of(layout.facts / "facts.jsonl", "observability.log.statement")
                  if str(f.attrs.get("level")) in _ALERTABLE_LEVELS]
    data = extract_json_object(provider(build_alert_prompt(ctx, statements)))
    if data is None:
        return {"task": "draft-alerts", "status": "deferred",
                "note": "unparseable reply — task left to the manual loop"}
    return _write_proposals(target, PROPOSALS_REL, "draft-alerts", data)


def _run_draft_runbooks(layout: RunLayout, provider, target: Path) -> dict:
    """Ask for runbook drafts over the run's uncovered Alerts; the ingest
    (`sre-kb generate-runbooks`) grounds every citation closed-world against the run."""
    from sre_kb.pipeline.runbooks_draft import PROPOSALS_REL
    from sre_kb.render import load_kb
    from sre_kb.synth.draft_prompts import build_runbook_prompt

    data = extract_json_object(provider(build_runbook_prompt(load_kb(layout.root))))
    if data is None:
        return {"task": "draft-runbooks", "status": "deferred",
                "note": "unparseable reply — task left to the manual loop"}
    return _write_proposals(target, PROPOSALS_REL, "draft-runbooks", data)


def _run_map_architecture(layout: RunLayout, provider, target: Path) -> dict:
    """Ask which design patterns/styles the code embodies beyond the deterministic skeleton; the
    ingest (`sre-kb map-architecture`) re-locates each anchor and refutes byte-proven duplicates."""
    from sre_kb.collectors.base import ScanContext
    from sre_kb.pipeline.architecture import PROPOSALS_REL, known_patterns
    from sre_kb.render import load_kb
    from sre_kb.synth.draft_prompts import build_architecture_prompt

    ctx = ScanContext(root=target, repo=f"file://{target.name}")
    docs = load_kb(layout.root)
    components = [c for d in docs if d.get("kind") == "Architecture"
                  for c in (d.get("spec", {}).get("components") or [])]
    prompt = build_architecture_prompt(ctx, components, sorted(known_patterns(docs)))
    data = extract_json_object(provider(prompt))
    if data is None:
        return {"task": "map-architecture", "status": "deferred",
                "note": "unparseable reply — task left to the manual loop"}
    return _write_proposals(target, PROPOSALS_REL, "map-architecture", data)


def _run_map_contracts(layout: RunLayout, provider, target: Path) -> dict:
    """Ask for semantic contract breaks over the current spec(s); the ingest
    (`sre-kb map-contracts`) re-locates each anchor and drops what the structural diff covers."""
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.common.openapi import current_specs
    from sre_kb.pipeline.confirm import load_facts_of
    from sre_kb.pipeline.contract import PROPOSALS_REL
    from sre_kb.synth.draft_prompts import build_contract_prompt

    ctx = ScanContext(root=target, repo=f"file://{target.name}")
    covered = sorted({str(f.attrs.get("ref"))
                      for f in load_facts_of(layout.facts / "facts.jsonl", "api.contract.change")})
    data = extract_json_object(provider(build_contract_prompt(ctx, current_specs(ctx), covered)))
    if data is None:
        return {"task": "map-contracts", "status": "deferred",
                "note": "unparseable reply — task left to the manual loop"}
    return _write_proposals(target, PROPOSALS_REL, "map-contracts", data)


def _run_narrative(layout: RunLayout, provider, target: Path) -> dict:
    """Ask for the advisory narrative over the closed-world brief; the ingest
    (`sre-kb findings-narrative --narrative`) grounds every `Kind/name` citation against the run."""
    from sre_kb.render import load_kb
    from sre_kb.render.project import service_name
    from sre_kb.reporting import collect_findings, narrative_brief
    from sre_kb.reporting.narrative import NARRATIVE_REL

    docs = load_kb(layout.root)
    brief = narrative_brief(service_name(docs), layout.run_id, collect_findings(docs), docs)
    reply = (provider(json.dumps(brief, indent=2)) or "").strip()
    if not reply:
        return {"task": "findings-narrative", "status": "deferred",
                "note": "empty reply — task left to the manual loop"}
    text = "\n".join(ln for ln in reply.splitlines() if not _FENCE_LINE.match(ln)).strip()
    out = target / NARRATIVE_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    return {"task": "findings-narrative", "status": "written", "output": str(out),
            "note": f"{len(text.splitlines())} line(s) of narrative"}


def run_scan_worklist(layout: RunLayout, worklist: dict, provider, *, target: Path) -> list[dict]:
    """Execute every task in the scan worklist through `provider`, returning one summary dict per
    task (`status`: written | deferred). An interactive provider (the model-free Copilot file
    exchange) can't answer synchronously, so the whole worklist defers to the manual loop."""
    if getattr(provider, "interactive", False):
        return [{"task": t["id"], "status": "deferred",
                 "note": "interactive provider — use the manual file exchange"}
                for t in worklist.get("tasks", [])]
    runners = {"discover-gaps": lambda: _run_discover(layout, provider, target),
               "confirm-challenge": lambda: _run_challenge(layout, provider),
               "confirm-boundaries": lambda: _run_confirm(layout, provider),
               "draft-alerts": lambda: _run_draft_alerts(layout, provider, target),
               "draft-runbooks": lambda: _run_draft_runbooks(layout, provider, target),
               "map-architecture": lambda: _run_map_architecture(layout, provider, target),
               "map-contracts": lambda: _run_map_contracts(layout, provider, target),
               "findings-narrative": lambda: _run_narrative(layout, provider, target)}
    summaries = []
    for task in worklist.get("tasks", []):
        runner = runners.get(task["id"])
        if runner is None:  # a worklist from a newer engine — surface, never silently drop
            summaries.append({"task": task["id"], "status": "deferred",
                              "note": "unknown task — left to the manual loop"})
            continue
        summary = runner()
        summary["ingest"] = task["ingest"]
        summaries.append(summary)
    return summaries
