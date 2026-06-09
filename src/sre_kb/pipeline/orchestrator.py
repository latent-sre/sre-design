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
from sre_kb.collectors.common import idempotency
from sre_kb.collectors.java_spring import messaging, resiliency_params
from sre_kb.collectors.llm import gap_finder
from sre_kb.config import load_config
from sre_kb.pipeline.confirm import _PRESENCE_CONCERNS, build_confirm_worklist
from sre_kb.pipeline.gap_finder import scaffold_gap
from sre_kb.reporting.findings import detect_tier_conflicts
from sre_kb.scoring.readiness import readiness_spec
from sre_kb.synth import scaffold
from sre_kb.synth.context_pack import build_context_pack
from sre_kb.synth.worklist import build_scan_worklist
from sre_kb.tiers import artifact_tier
from sre_kb.validation.challenge import (
    GroundingChallenger,
    apply_challenge_gating,
    build_worklist,
    challenge_doc,
)
from sre_kb.validation.crossref import check_crossrefs, status_aware_downgrades
from sre_kb.validation.gating import final_status
from sre_kb.validation.provenance import verify_evidence
from sre_kb.validation.report import write_report
from sre_kb.validation.safety import lint_doc
from sre_kb.validation.structural import validate_doc
from sre_kb.validation.substance import check_substance
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


def _dest_dir(layout: RunLayout, status: str, kind: str) -> Path:
    """Where a finalized artifact is written: rejected -> reports/rejected, else the KB status dir.
    Shared by the main persist loop and the readiness recompute so they can't diverge (a rejected
    ReadinessScore must not also land in kb/needs-review via kb_dir's non-verified mapping)."""
    base = (layout.reports / "rejected" if status == "rejected" else layout.kb_dir(status)) / kind
    base.mkdir(parents=True, exist_ok=True)
    return base


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

    # Tier-B (HYBRID-PLAN §7.9/§9.3): if Copilot left gap proposals (`.sre/gap-proposals.json`),
    # re-ground them and merge the survivors as Tier-B facts — a complete no-op when the file is
    # absent. Merging them into `fs` here means they land in `facts.jsonl` and are seen by the
    # §7.1 tier-conflict check; the matching `ResiliencyGap` docs are appended after scaffold and
    # flow through the SAME validate/challenge/gate path. The contract (needs-review, never
    # auto-verify) holds because `scaffold_gap` fixes the status + sub-floor confidence, which the
    # shared gate only ever preserves or lowers.
    gap_cfg = cfg.get("gap_finder") or {}
    # Tier-A deterministic parameter-completeness gaps (R5) + Tier-B re-grounded proposals (§7.9).
    # Both are `resiliency.gap` facts surfaced as ResiliencyGap artifacts via scaffold_gap below; the
    # Tier-A ones carry source_tier=ast and can verify, the Tier-B ones stay needs-review.
    gap_facts = (resiliency_params.collect(ctx) + messaging.collect_gaps(ctx, fs)
                 + idempotency.collect_gaps(ctx, fs)
                 + gap_finder.collect(ctx, fs=fs, max_candidates=gap_cfg.get("max_candidates"),
                                      max_novel=gap_cfg.get("max_novel")).facts)
    if gap_facts:
        fs.add(*gap_facts)

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
    if gap_facts:  # Tier-A (R5) + Tier-B gap artifacts join the candidate set, same service
        app = fs.first("pcf.app")
        service = (app.attrs.get("name") if app else None) or "service"
        docs += [scaffold_gap(f, service) for f in gap_facts]
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

    crossref_problems = check_crossrefs(docs)
    challenger = GroundingChallenger()
    # Pass 1: per-artifact status (everything except the status-aware crossref constraint).
    staged = []
    for d in docs:
        key = f"{d['kind']}/{d['metadata']['name']}"
        struct = validate_doc(d)
        prov = verify_evidence(d, target_path)
        xref = crossref_problems.get(key, [])
        safety = lint_doc(d)
        substance = check_substance(d)
        status = final_status(
            d,
            structural_ok=not struct,
            provenance_ok=not prov,
            crossref_ok=not xref,
            min_confidence=gate.get("verified_min_confidence", 0.7),
            require_verified_provenance=gate.get("require_verified_provenance", True),
        )
        if (safety or substance) and status == "verified":  # dangerous/empty content -> human
            status = "needs-review"
        verdicts = challenge_doc(d, ctx.read_lines, challenger)  # adversarial grounding pass
        status, challenge_notes = apply_challenge_gating(status, verdicts)
        staged.append(
            {"d": d, "key": key, "tier": artifact_tier(d), "status": status, "struct": struct,
             "prov": prov, "xref": xref, "safety": safety, "substance": substance,
             "verdicts": verdicts, "challenge_notes": challenge_notes}
        )

    # Pass 2: status-aware crossref — downgrade any verified artifact that depends on a
    # non-verified referent (monotonic fixpoint), so a "verified" graph stays self-consistent.
    downgrades = status_aware_downgrades(
        {s["key"]: s["status"] for s in staged},
        {s["key"]: (s["d"].get("crossRefs") or []) for s in staged},
    )

    # Pass 3: finalize status, persist artifacts, and build the report records.
    layout.reset_kb()  # clear any prior run's KB so re-runs (diff's fixed ids) can't leak stale docs
    by_status: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    records = []
    for s in staged:
        d, key, status = s["d"], s["key"], s["status"]
        if key in downgrades:
            status = "needs-review"
        d["status"] = status
        out = _dest_dir(layout, status, d["kind"])
        _dump_yaml(out / f"{d['metadata']['name']}.yaml", d)
        by_status[status] = by_status.get(status, 0) + 1
        by_tier[s["tier"]] = by_tier.get(s["tier"], 0) + 1
        rec = {
            "artifact": key, "status": status, "tier": s["tier"], "structural": s["struct"],
            "provenance": s["prov"], "crossref": s["xref"], "safety": s["safety"],
            "substance": s["substance"],
            "challenger": challenger.id, "challenge": [v.__dict__ for v in s["verdicts"]],
            "challengeNotes": s["challenge_notes"],
        }
        if key in downgrades:
            rec["crossrefStatus"] = downgrades[key]
        records.append(rec)

    # Recompute the readiness roll-up against FINAL statuses — it was built at scaffold time on
    # pre-gating statuses, so a gating downgrade (e.g. status-aware crossref) wouldn't otherwise
    # be reflected. Status-aware readiness credits only verified coverage (HYBRID-PLAN Phase 2).
    final_docs = [s["d"] for s in staged]
    others = [d for d in final_docs if d.get("kind") != "ReadinessScore"]
    for d in final_docs:
        if d.get("kind") == "ReadinessScore":
            d["spec"] = readiness_spec(fs, others, fs.of("budget.finding"))
            _dump_yaml(
                _dest_dir(layout, d["status"], "ReadinessScore") / f"{d['metadata']['name']}.yaml", d
            )

    report = {
        "run_id": run_id,
        "target": str(target_path),
        "facts": len(fs.facts),
        "docs": len(docs),
        "by_status": by_status,
        "by_tier": by_tier,
        "tierConflicts": detect_tier_conflicts(fs.facts),  # §7.1: Tier-A vs Tier-B disagreements
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

    # Confirm loop (S4): hand the skill the engine's own Tier-A boundary calls to affirm/dispute —
    # absence gaps ("present here") and present mechanisms ("disabled here"). Verdicts re-gate via
    # `sre-kb confirm-apply`: an absence dispute drops a false-positive gap; a presence dispute that
    # re-derives a disable emits a new Tier-A disabled-resilience gap.
    confirm_worklist = build_confirm_worklist(run_id, gap_facts, fs.of(*_PRESENCE_CONCERNS))
    if confirm_worklist["items"]:
        fdir = layout.root / "confirm"
        fdir.mkdir(parents=True, exist_ok=True)
        (fdir / "boundary-calls.json").write_text(
            json.dumps(confirm_worklist, indent=2), encoding="utf-8")

    # Unified LLM scan worklist: one manifest of every discover/confirm task Copilot should run for
    # this run — the single front door for the manual loop. The engine still never calls a model.
    app = fs.first("pcf.app")
    service = (app.attrs.get("name") if app else None) or "service"
    scan_worklist = build_scan_worklist(
        run_id,
        service=service,
        target=str(target_path),
        context_packs=sum(1 for d in docs if d.get("evidence")),
        challenge_items=len(worklist["items"]),
        confirm_boundaries=len(confirm_worklist["items"]),
    )
    (layout.root / "scan-worklist.json").write_text(
        json.dumps(scan_worklist, indent=2), encoding="utf-8"
    )

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
