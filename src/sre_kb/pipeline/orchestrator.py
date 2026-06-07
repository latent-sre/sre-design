"""Deterministic pipeline. Stages: clone(local) -> scan(+scaffold) -> validate.

The LLM enrichment step (Copilot in VS Code) sits between scaffold and validate and is
NOT run here — the engine never calls a model. For a local target, 'clone' just points
the scan context at the path.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from sre_kb.collectors import scan as run_collectors
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.config import load_config
from sre_kb.synth import scaffold
from sre_kb.synth.context_pack import build_context_pack
from sre_kb.validation.challenge import (
    GroundingChallenger,
    apply_challenge_gating,
    build_worklist,
    challenge_doc,
)
from sre_kb.validation.crossref import resolve_statuses
from sre_kb.validation.gating import final_status
from sre_kb.validation.provenance import verify_evidence
from sre_kb.validation.report import write_report
from sre_kb.validation.safety import lint_doc
from sre_kb.validation.structural import validate_doc
from sre_kb.workspace import RunLayout

STAGES = ("scan", "scaffold", "validate", "render", "publish")


@dataclass
class RunResult:
    run_id: str
    root: Path
    facts: int
    docs: int
    by_status: dict
    report_path: Path | None = None
    projections: Path | None = None
    pr: Path | None = None


def _dump_yaml(path: Path, doc: dict) -> None:
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")


def run(target: str, *, work_root: str = ".work", run_id: str | None = None, to_stage: str = "validate") -> RunResult:
    cfg = load_config()
    gate = cfg.get("gating", {})
    run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    layout = RunLayout(Path(work_root), run_id)
    layout.ensure()

    target_path = Path(target).resolve()
    if not target_path.exists():
        raise FileNotFoundError(f"target not found: {target_path}")

    ctx = ScanContext(root=target_path, repo=f"file://{target_path.name}", commit=LOCAL_COMMIT)
    fs = run_collectors(ctx)

    with (layout.facts / "facts.jsonl").open("w", encoding="utf-8") as fh:
        for f in fs.facts:
            fh.write(
                json.dumps(
                    {
                        "type": f.type,
                        "attrs": f.attrs,
                        "symbol": f.symbol.fqn if f.symbol else None,
                        "evidence": f.evidence.model_dump(mode="json"),
                    }
                )
                + "\n"
            )
    if to_stage == "scan":
        return RunResult(run_id, layout.root, len(fs.facts), 0, {})

    docs = scaffold(fs, ctx)
    ctx_dir = layout.candidates / "context"
    ctx_dir.mkdir(exist_ok=True)
    for d in docs:
        _dump_yaml(layout.candidates / f"{d['kind']}-{d['metadata']['name']}.yaml", d)
        if d.get("evidence"):  # untrusted-input-framed context pack for Copilot
            (ctx_dir / f"{d['kind']}-{d['metadata']['name']}.md").write_text(
                build_context_pack(ctx, d), encoding="utf-8"
            )
    if to_stage == "scaffold":
        return RunResult(run_id, layout.root, len(fs.facts), len(docs), {})

    challenger = GroundingChallenger()
    # Phase 1: per-doc validation -> a PRELIMINARY status (everything except crossref). Crossref
    # is held back because making it status-aware needs the other docs' statuses first.
    prelim: dict[str, str] = {}
    pieces: dict[str, dict] = {}
    for d in docs:
        key = f"{d['kind']}/{d['metadata']['name']}"
        struct = validate_doc(d)
        prov = verify_evidence(d, target_path)
        safety = lint_doc(d)
        status = final_status(
            d,
            structural_ok=not struct,
            provenance_ok=not prov,
            crossref_ok=True,  # deferred to the fixpoint below
            min_confidence=gate.get("verified_min_confidence", 0.7),
            require_verified_provenance=gate.get("require_verified_provenance", True),
        )
        if safety and status == "verified":  # dangerous content must get a human
            status = "needs-review"
        verdicts = challenge_doc(d, ctx.read_lines, challenger)  # adversarial grounding pass
        status, challenge_notes = apply_challenge_gating(status, verdicts)
        prelim[key] = status
        pieces[key] = {"struct": struct, "prov": prov, "safety": safety,
                       "verdicts": verdicts, "challengeNotes": challenge_notes}

    # Phase 2: status-aware crossref to a fixpoint. A verified artifact citing an unverified
    # (or dangling) referent over a trust-bearing relation is downgraded to needs-review;
    # downgrades cascade until stable (see crossref.resolve_statuses).
    status_of = {(d["kind"], d["metadata"]["name"]):
                 prelim[f"{d['kind']}/{d['metadata']['name']}"] for d in docs}
    crossref_problems = resolve_statuses(docs, status_of)
    for d in docs:
        prelim[f"{d['kind']}/{d['metadata']['name']}"] = status_of[(d["kind"], d["metadata"]["name"])]

    # Phase 3: finalize — write each doc at its settled status and record it.
    by_status: dict[str, int] = {}
    records = []
    for d in docs:
        key = f"{d['kind']}/{d['metadata']['name']}"
        status = prelim[key]
        p = pieces[key]
        xref = crossref_problems.get(key, [])
        d["status"] = status
        if status == "rejected":
            out = layout.reports / "rejected" / d["kind"]
        else:
            out = layout.kb_dir(status) / d["kind"]
        out.mkdir(parents=True, exist_ok=True)
        _dump_yaml(out / f"{d['metadata']['name']}.yaml", d)
        by_status[status] = by_status.get(status, 0) + 1
        records.append(
            {"artifact": key, "status": status, "structural": p["struct"], "provenance": p["prov"],
             "crossref": xref, "safety": p["safety"], "challenger": challenger.id,
             "challenge": [v.__dict__ for v in p["verdicts"]], "challengeNotes": p["challengeNotes"]}
        )

    report = {
        "run_id": run_id,
        "target": str(target_path),
        "facts": len(fs.facts),
        "docs": len(docs),
        "by_status": by_status,
        "records": records,
    }
    report_path = layout.reports / "validation_report.json"
    write_report(report_path, report)

    # Worklist of judgment-call claims for the LLM challenger (Copilot). Each item carries
    # an untrusted-input-framed prompt; verdicts re-gate via `sre-kb challenge-apply`.
    worklist = build_worklist(run_id, docs, lambda d: build_context_pack(ctx, d))
    if worklist["items"]:
        cdir = layout.root / "challenge"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "worklist.json").write_text(json.dumps(worklist, indent=2), encoding="utf-8")

    projections = pr_tree = None
    if to_stage in ("render", "publish"):
        from sre_kb.render import render_projections

        projections = render_projections(layout, docs)
    if to_stage == "publish":
        from sre_kb.publish import assemble_pr

        pr_tree, _ = assemble_pr(layout, docs, report, dry_run=True)

    return RunResult(
        run_id, layout.root, len(fs.facts), len(docs), by_status, report_path, projections, pr_tree
    )
