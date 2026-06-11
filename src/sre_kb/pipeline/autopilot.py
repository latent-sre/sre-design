"""One-command convergence of the LLM loop: scan → provider → apply → re-scan (`sre-kb autopilot`).

The pieces all exist — `run` (deterministic scan + worklist emission), `worklist_run` (drive every
LLM task through the provider seam), and the deterministic ingest gates (`challenge-apply`,
`confirm-apply`, proposal re-grounding on the next scan). This module chains them into the
discover→re-ground cycle SCOPE-AND-COVERAGE §6 describes: run 1 emits claims and context, the
provider answers, verdicts re-gate run 1 and proposals land in the target; run 2 re-scans and
re-grounds every proposal byte-by-byte. The default two cycles are that loop made literal.

After the last cycle the drafting outputs are folded in: surviving Tier-B Alert/Runbook drafts
(`needs-review`, `source_tier=llm` by construction) join the final run's KB tree, the contract
review and the grounded narrative land in `reports/`. Graduation is recorded only on the final
cycle, so repeated cycles can't double-count one confirmation. The trust boundary never moves:
every applied verdict is monotonic (downgrade-only) and every kept draft was re-derived or
closed-world-grounded by the engine.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from sre_kb.pipeline.challenge_apply import apply_verdicts
from sre_kb.pipeline.confirm import record_confirm_graduation, regate_run
from sre_kb.pipeline.orchestrator import run
from sre_kb.pipeline.worklist_run import run_scan_worklist
from sre_kb.workspace import RunLayout


@dataclass
class CycleOutcome:
    """One scan→provider→apply cycle: what the LLM half did and what the engine applied."""

    run_id: str
    tasks: list[dict] = field(default_factory=list)
    challenge_changed: int = 0  # artifacts the applied challenge verdicts downgraded
    confirm_outcomes: int = 0   # boundary calls re-ground by confirm-apply


@dataclass
class AutopilotResult:
    run_id: str  # the final cycle's run — the converged KB
    cycles: list[CycleOutcome] = field(default_factory=list)
    drafted_alerts: int = 0
    drafted_runbooks: int = 0
    proposed_patterns: int = 0
    contract_routed: int = 0
    narrative_note: str | None = None
    pcf_review_routed: int = 0
    narrations_applied: int = 0
    area_recommendations: int = 0


def _apply_cycle(layout: RunLayout, target: Path, outcome: CycleOutcome, *, record: bool) -> None:
    """Apply the cycle's verdicts in-process — the same monotonic gates the standalone
    `challenge-apply` / `confirm-apply` commands run. Graduation is recorded only when `record`
    (the final cycle), so re-adjudicating the same claims each cycle can't double-count."""
    vpath = layout.root / "challenge" / "verdicts.json"
    if vpath.exists():
        summary = apply_verdicts(layout, json.loads(vpath.read_text(encoding="utf-8")))
        outcome.challenge_changed = sum(1 for s in summary if s.get("new") != s.get("old"))
    cpath = layout.root / "confirm" / "verdicts.json"
    if cpath.exists():
        outcomes = regate_run(layout, str(target), json.loads(cpath.read_text(encoding="utf-8")))
        outcome.confirm_outcomes = len(outcomes)
        if record:
            record_confirm_graduation(target, outcomes, layout.run_id)


def _write_kb_doc(layout: RunLayout, doc: dict) -> None:
    dest = layout.kb / doc["status"] / doc["kind"]
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{doc['metadata']['name']}.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _ingest_drafts(layout: RunLayout, target: Path, result: AutopilotResult) -> None:
    """Fold the drafting outputs into the final run: re-ground each proposals file through its
    engine half and land the survivors. Every drafter self-gates on a missing/malformed file, so a
    deferred task simply contributes nothing."""
    from sre_kb.pipeline import alerts_draft, architecture, contract, runbooks_draft
    from sre_kb.pipeline.diagram_narration import apply_narrations
    from sre_kb.pipeline.diagram_narration import PROPOSALS_REL as NARRATIONS_REL
    from sre_kb.pipeline.pcf_review import PROPOSALS_REL as PCF_REVIEW_REL
    from sre_kb.pipeline.pcf_review import run_pcf_review
    from sre_kb.render import load_kb
    from sre_kb.render.project import service_name
    from sre_kb.reporting import collect_findings, render_narrative, validate_narrative
    from sre_kb.reporting.narrative import NARRATIVE_REL

    docs = load_kb(layout.root)
    service = service_name(docs)
    if (target / alerts_draft.PROPOSALS_REL).exists():
        drafted = alerts_draft.run_generate_alerts(str(target), service=service)
        for doc in drafted.docs:
            _write_kb_doc(layout, doc)
        result.drafted_alerts = len(drafted.docs)
    if (target / runbooks_draft.PROPOSALS_REL).exists():
        drafted = runbooks_draft.run_generate_runbooks(str(target), service=service)
        for doc in drafted.docs:
            _write_kb_doc(layout, doc)
        result.drafted_runbooks = len(drafted.docs)
    if (target / architecture.PROPOSALS_REL).exists():
        mapped = architecture.run_map_architecture(str(target), service=service)
        for doc in mapped.docs:
            _write_kb_doc(layout, doc)
        result.proposed_patterns = len(mapped.kept())
    if (target / contract.PROPOSALS_REL).exists():
        reviewed = contract.run_map_contracts(str(target))
        result.contract_routed = len(reviewed.kept())
        (layout.reports / "contract-review.json").write_text(json.dumps(
            [{"target": o.proposal.target, "result": o.result, "path": o.path,
              "lines": list(o.lines) if o.lines else None, "note": o.note}
             for o in reviewed.outcomes], indent=2), encoding="utf-8")
    # Reload: the drafters above just wrote new KB docs (alerts/runbooks/architecture); the
    # projection render and narrations below must see them, not the list from function entry.
    docs = load_kb(layout.root)
    if (target / PCF_REVIEW_REL).exists():
        result.pcf_review_routed = len(run_pcf_review(str(target)).kept())
    from sre_kb.pipeline.areas import PROPOSALS_REL as AREAS_REL
    from sre_kb.pipeline.areas import run_discover_areas

    if (target / AREAS_REL).exists():
        result.area_recommendations = len(run_discover_areas(
            str(target), layout.facts / "facts.jsonl", layout.reports).kept())
    if (target / NARRATIONS_REL).exists():
        from sre_kb.render import render_projections

        # Narrations decorate rendered diagram markdown; autopilot cycles stop at validate,
        # so render the final run's projections (deterministic, idempotent) before applying.
        render_projections(layout, docs)
        result.narrations_applied = len(
            apply_narrations(layout, docs, target / NARRATIONS_REL).applied())
    npath = target / NARRATIVE_REL
    if npath.exists():
        found = collect_findings(docs)
        text = npath.read_text(encoding="utf-8")
        check = validate_narrative(text, found, docs)
        (layout.reports / "findings-narrative.md").write_text(
            render_narrative(service, text, check), encoding="utf-8")
        result.narrative_note = check.note


def run_autopilot(target: str, provider, *, work_root: str = ".work",
                  run_base: str | None = None, cycles: int = 2) -> AutopilotResult:
    """Converge the loop: each cycle scans (re-grounding the prior cycle's proposals), drives the
    scan worklist through `provider`, and applies the verdicts; after the last cycle the drafting
    outputs are folded into the final run's KB. Stops early when a scan emits no LLM work."""
    target_path = Path(target).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"target not found: {target_path}")
    base = run_base or time.strftime("%Y%m%d-%H%M%S")
    result = AutopilotResult(run_id=base)
    layout = None
    for i in range(1, cycles + 1):
        run_id = f"{base}-c{i}"
        run(str(target_path), work_root=work_root, run_id=run_id, to_stage="validate")
        layout = RunLayout(Path(work_root), run_id)
        result.run_id = run_id
        outcome = CycleOutcome(run_id)
        result.cycles.append(outcome)
        wpath = layout.root / "scan-worklist.json"
        worklist = json.loads(wpath.read_text(encoding="utf-8")) if wpath.exists() else {"tasks": []}
        if not worklist["tasks"]:
            break  # nothing for the LLM half — already converged
        outcome.tasks = run_scan_worklist(layout, worklist, provider, target=target_path)
        _apply_cycle(layout, target_path, outcome, record=(i == cycles))
    if layout is not None:
        _ingest_drafts(layout, target_path, result)
    return result
