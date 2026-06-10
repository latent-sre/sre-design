"""`sre-kb` command-line interface.

All subcommands are implemented: `run`/`scan`/`render`/`publish` (the deterministic pipeline),
`validate-kb`, `findings`, `estate`, `diff`, `scan-worklist`/`worklist-run`/`autopilot`,
`challenge-worklist`/`challenge-apply`, `gap-finder`, `secret-scan`, and `schema`. There is no separate
`validate` subcommand — validation is the default `--to-stage` of `run`. The engine embeds no LLM —
enrichment runs through the `LLMProvider` seam between `scan` and the validate stage: by default
Copilot in VS Code via the manual file exchange (`scan-worklist` is its single front door — one
manifest of every discover/confirm/drafting task), `worklist-run --oracle` drives the same tasks
through a programmatic provider, and `autopilot` converges the whole loop (scan → provider → apply →
re-scan) in one command.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from sre_kb import __version__
from sre_kb.config import registry_path
from sre_kb.validation import validate_kb_tree

app = typer.Typer(
    add_completion=False,
    help="Turn a code repo into a populated, validated SRE knowledge base + Copilot skills.",
    no_args_is_help=True,
)
schema_app = typer.Typer(help="Introspect the kind registry and schemas.", no_args_is_help=True)
app.add_typer(schema_app, name="schema")

def _load_registry() -> dict:
    with registry_path().open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@app.command()
def version() -> None:
    """Print the sre-kb version."""
    typer.echo(f"sre-kb {__version__}")


@app.command()
def plan(
    target: Path = typer.Option(..., "--target", help="Repo (possibly a monorepo) to discover services in."),
    max_services: int | None = typer.Option(None, "--max-services", help="Fan-out cap (default scan.max_services)."),
) -> None:
    """Discover the deployable services in a repo and print the fan-out-capped scan plan (R8)."""
    from sre_kb.scan_plan import ScanFanOutError, plan_services

    try:
        services = plan_services(target, max_services=max_services)
    except ScanFanOutError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    for s in services:
        typer.echo(f"{s.name}\t{s.path}")
    typer.echo(f"\n{len(services)} service(s) to scan.")


@app.command("run-plan")
def run_plan_cmd(
    target: Path = typer.Option(..., "--target", help="Repo to discover and scan service-by-service."),
    work_root: str = typer.Option(".work", "--work-root"),
    run_id: str | None = typer.Option(None, "--run"),
    to_stage: str = typer.Option("validate", "--to-stage"),
    max_services: int | None = typer.Option(None, "--max-services", help="Fan-out cap (default scan.max_services)."),
) -> None:
    """Scan every discovered service through the pipeline, checkpointing after each (resumable; R8)."""
    from sre_kb.scan_plan import ScanFanOutError, run_plan

    try:
        summary = run_plan(
            target, work_root=work_root, run_id=run_id, to_stage=to_stage, max_services=max_services
        )
    except ScanFanOutError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"plan {summary['run_id']}: scanned {len(summary['scanned'])}, "
        f"skipped {len(summary['skipped'])} of {len(summary['services'])} service(s)"
    )


@schema_app.command("list")
def schema_list() -> None:
    """List registered kinds and their phase."""
    kinds = _load_registry().get("kinds", {})
    if not kinds:
        typer.echo("no kinds registered")
        raise typer.Exit(code=0)
    width = max(len(k) for k in kinds)
    for kind in sorted(kinds):
        entry = kinds[kind] or {}
        typer.echo(f"{kind.ljust(width)}  {entry.get('phase', '?'):<3}  {entry.get('schema', '')}")


@schema_app.command("show")
def schema_show(kind: str) -> None:
    """Show the registry entry for a kind."""
    kinds = _load_registry().get("kinds", {})
    if kind not in kinds:
        typer.echo(f"unknown kind: {kind}", err=True)
        raise typer.Exit(code=2)
    typer.echo(yaml.safe_dump({kind: kinds[kind]}, sort_keys=False).rstrip())


@app.command("validate-kb")
def validate_kb(
    directory: Path = typer.Argument(..., help="Directory of KB YAML artifacts."),
    schema_dir: Path | None = typer.Option(None, "--schema-dir", help="Schema directory to validate against."),
) -> None:
    """Validate an existing KB tree against the schemas. Exits non-zero on any failure."""
    if not directory.exists():
        typer.echo(f"no such directory: {directory}", err=True)
        raise typer.Exit(code=2)
    if schema_dir is not None and not schema_dir.exists():
        typer.echo(f"no such schema dir: {schema_dir}", err=True)
        raise typer.Exit(code=2)
    results = validate_kb_tree(directory, schema_root=schema_dir)
    failures = [r for r in results if not r.ok]
    for r in results:
        mark = "ok  " if r.ok else "FAIL"
        typer.echo(f"[{mark}] {r.path} ({r.kind or '?'})")
        for err in r.errors:
            typer.echo(f"         - {err}")
    typer.echo(f"\n{len(results)} artifact(s), {len(failures)} failed.")
    raise typer.Exit(code=1 if failures else 0)


@app.command("eval")
def eval_cmd(
    target: str = typer.Option(..., "--target", help="Local path of the labeled fixture repo."),
    truth: Path = typer.Option(None, "--truth", help="Eval truth JSON (default: <target>/.sre/eval-truth.json)."),
    report: Path = typer.Option(None, "--report", help="Write the full scorecard JSON here."),
    work_root: str = typer.Option(".work", "--work-root"),
    run_id: str = typer.Option("eval", "--run"),
) -> None:
    """Score the deterministic extraction over a labeled fixture (S5 rubric-as-spec): per-area
    precision/recall + per-detector coverage. The engine still never calls a model — this measures
    the deterministic output against the labeled truth set."""
    import json

    from sre_kb.eval.scorecard import load_eval_truth, score_target

    truth_path = truth or (Path(target) / ".sre" / "eval-truth.json")
    if not truth_path.exists():
        typer.echo(f"no eval truth at {truth_path}", err=True)
        raise typer.Exit(code=2)
    sc = score_target(target, load_eval_truth(truth_path), work_root=work_root, run_id=run_id)
    data = sc.as_dict()
    o = data["overall"]

    def _pct(v: float | None) -> str:
        return "  n/a" if v is None else f"{v * 100:5.1f}%"

    typer.echo(f"overall: recall {_pct(o['recall'])}  precision {_pct(o['precision'])}  "
               f"detector-coverage {_pct(o['detectorRecall'])}")
    for kind, row in data["perArea"].items():
        flags = []
        if row["missed"]:
            flags.append(f"missed={row['missed']}")
        if row["unexpected"]:
            flags.append(f"unexpected={row['unexpected']}")
        typer.echo(f"  {kind:18} recall {_pct(row['recall'])}  precision {_pct(row['precision'])}  "
                   f"{' '.join(flags)}")
    missing = data["detectorCoverage"]["missing"]
    if missing:
        typer.echo(f"  detectors not firing: {missing}")
    if report:
        report.write_text(json.dumps(data, indent=2), encoding="utf-8")
        typer.echo(f"wrote scorecard → {report}")


@app.command("confirm-gap")
def confirm_gap(
    category: str = typer.Argument(..., help="Gap category a reviewer is confirming (or dismissing)."),
    target: Path = typer.Option(Path("."), "--target", help="Target repo whose .sre/ holds the tracker."),
    anchor: str | None = typer.Option(None, "--anchor", help="Excerpt/pointer of the confirmed instance."),
    run_id: str | None = typer.Option(None, "--run", help="Run id, for the audit trail."),
    false_positive: bool = typer.Option(
        False, "--false-positive", help="Record a dismissed/false gap instead of a confirmation."
    ),
    novel: bool = typer.Option(
        False, "--novel",
        help="Accept an out-of-taxonomy category proposed by the open-discovery channel.",
    ),
) -> None:
    """Record a human verdict on a needs-review gap, feeding the graduation tally (HYBRID-PLAN §9.3 #3)."""
    from sre_kb.collectors.llm.gap_finder import gap_categories, is_valid_novel_category
    from sre_kb.graduation import GraduationTracker
    from sre_kb.pipeline.confirm import confirm_emitted_categories

    known = gap_categories() | confirm_emitted_categories()
    if category not in known and not novel:
        typer.echo(f"unknown gap category: {category}", err=True)
        typer.echo(f"known: {', '.join(sorted(known))}", err=True)
        typer.echo("(an out-of-taxonomy category from the open-discovery channel needs --novel)", err=True)
        raise typer.Exit(code=2)
    if category not in known and not is_valid_novel_category(category):
        typer.echo(f"invalid novel category name (want kebab-case): {category}", err=True)
        raise typer.Exit(code=2)
    tracker = GraduationTracker.load(target)
    cat = tracker.refute(category) if false_positive else tracker.confirm(category, run=run_id, anchor=anchor)
    tracker.save(target)
    verdict = "false-positive" if false_positive else "confirmation"
    typer.echo(
        f"recorded {verdict} for {category}: "
        f"{cat.confirmed} confirmation(s), {cat.false_positives} false-positive(s)"
    )


@app.command("graduation-candidates")
def graduation_candidates(
    target: Path = typer.Option(Path("."), "--target", help="Target repo whose .sre/ holds the tracker."),
) -> None:
    """Show graduation status; for each promotion-ready category, draft the deterministic signature to
    review and merge (assisted promotion — the engine never edits its own rules)."""
    from sre_kb.collectors.llm.gap_finder import gap_categories, target_concerns
    from sre_kb.config import load_config
    from sre_kb.graduation import GraduationTracker, draft_signature
    from sre_kb.pipeline.confirm import confirm_emitted_categories

    threshold = int((load_config().get("graduation") or {}).get("confirmation_threshold", 5))
    tracker = GraduationTracker.load(target)
    if not tracker.categories:
        typer.echo("no gap confirmations recorded yet")
        raise typer.Exit(code=0)
    known = gap_categories() | confirm_emitted_categories()
    ready = 0
    for name, cat in sorted(tracker.categories.items()):
        is_ready = cat.is_candidate(threshold)
        ready += is_ready
        state = "promoted" if cat.promoted else ("READY to graduate" if is_ready else f"{cat.confirmed}/{threshold}")
        typer.echo(f"{name}: {state}  (confirmed={cat.confirmed}, false-positives={cat.false_positives})")
        if is_ready:
            typer.echo(draft_signature(cat, target_concerns(name), known=name in known))
    typer.echo(f"\n{ready} categor{'y' if ready == 1 else 'ies'} ready to graduate (threshold {threshold}).")


@app.command()
def run(
    target: str = typer.Option(..., "--target", help="Local path or git URL of the target repo."),
    profile: str = typer.Option("java-spring-pcf", "--profile"),
    to_stage: str = typer.Option("validate", "--to-stage", help="scan | scaffold | validate"),
    work_root: str = typer.Option(".work", "--work-root"),
    run_id: str = typer.Option(None, "--run", help="Run id (default: timestamp)."),
) -> None:
    """Run the deterministic pipeline: clone(local) -> scan -> validate.

    LLM enrichment (Copilot in VS Code) happens between scan and validate; the engine
    itself never calls a model.
    """
    from sre_kb.pipeline import run as run_pipeline

    result = run_pipeline(target, work_root=work_root, run_id=run_id, to_stage=to_stage)
    typer.echo(f"run {result.run_id}: {result.facts} facts, {result.docs} artifact(s)")
    for status, n in sorted(result.by_status.items()):
        typer.echo(f"  {status}: {n}")
    typer.echo(f"  output: {result.root}")
    if result.report_path:
        typer.echo(f"  report: {result.report_path}")
    if result.projections:
        typer.echo(f"  projections: {result.projections}")
    if result.pr:
        typer.echo(f"  pr tree: {result.pr}")


@app.command()
def scan(
    target: str = typer.Option(..., "--target", help="Local path of the target repo."),
    work_root: str = typer.Option(".work", "--work-root"),
    run_id: str = typer.Option(None, "--run"),
) -> None:
    """Deterministic facts + scaffold (no LLM)."""
    from sre_kb.pipeline import run as run_pipeline

    result = run_pipeline(target, work_root=work_root, run_id=run_id, to_stage="scaffold")
    typer.echo(f"run {result.run_id}: {result.facts} facts, {result.docs} scaffolded -> {result.root}")


@app.command()
def render(
    run_id: str = typer.Option(..., "--run"),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Render the Copilot projection (guardrails + diagrams) + Backstage catalog."""
    from sre_kb.render import load_kb, render_projections
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    proj = render_projections(layout, load_kb(layout.root))
    typer.echo(f"projections: {proj}")


@app.command()
def publish(
    run_id: str = typer.Option(..., "--run"),
    sre_repo: str = typer.Option("(unset)", "--sre-repo"),
    forge: str = typer.Option("github", "--forge"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
    allow_secrets: bool = typer.Option(False, "--allow-secrets", help="Override the secret-scan gate (unsafe)."),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Stage the per-service PR tree and (optionally) open the PR. Defaults to --dry-run.

    A publish-time secret-scan gate hard-fails if the PR tree contains secrets.
    """
    import json

    from sre_kb.config import load_config
    from sre_kb.publish import assemble_pr
    from sre_kb.publish.forge import ForgePublishError
    from sre_kb.render import load_kb
    from sre_kb.security import SecretLeakError
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    docs = load_kb(layout.root)
    report_path = layout.reports / "validation_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else None
    allowed_repos = (load_config().get("publish") or {}).get("allowed_repos")
    try:
        tree, ref = assemble_pr(
            layout, docs, report, sre_repo=sre_repo, forge=forge, dry_run=dry_run,
            allow_secrets=allow_secrets, allowed_repos=allowed_repos,
        )
    except SecretLeakError as exc:
        typer.echo(f"BLOCKED by secret-scan gate: {exc}", err=True)
        for f in exc.findings:
            typer.echo(f"  {f['rule']}  {f['path']}:{f['line']}", err=True)
        raise typer.Exit(code=2) from exc
    except ForgePublishError as exc:
        typer.echo(f"publish failed: {exc}", err=True)
        raise typer.Exit(code=3) from exc
    typer.echo(f"PR tree: {tree}")
    typer.echo(ref)


@app.command()
def findings(
    run_id: str = typer.Option(..., "--run"),
    fmt: str = typer.Option("text", "--format", help="text | json | md"),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Print a ranked SRE risk digest (data-loss, uncontained critical deps) for a run."""
    import json

    from sre_kb.render import load_kb
    from sre_kb.render.project import service_name
    from sre_kb.reporting import collect_findings, render_md, render_text
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    docs = load_kb(layout.root)
    found = collect_findings(docs)
    service = service_name(docs)
    if fmt == "json":
        typer.echo(json.dumps({"service": service, "runId": run_id, "findings": found}, indent=2))
    elif fmt == "md":
        typer.echo(render_md(service, run_id, found, docs))
    else:
        typer.echo(render_text(service, run_id, found, docs))
    if any(f["severity"] in ("critical", "high") for f in found):
        raise typer.Exit(code=1)  # non-zero so CI can gate on high-severity findings


@app.command("findings-narrative")
def findings_narrative(
    run_id: str = typer.Option(..., "--run"),
    narrative: Path = typer.Option(
        None, "--narrative", help="LLM narrative file to validate (omit to emit the brief for Copilot)."
    ),
    fmt: str = typer.Option(None, "--format", help="brief: json (default) | text; validate: md (default) | json"),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Advisory Tier-B narrative over the findings digest (HYBRID-PLAN §9.7 N5).

    With no --narrative, emit the deterministic brief (ranked findings + the closed set of artifact
    references) for Copilot to summarize. With --narrative, ground the returned prose against the
    digest: every `Kind/name` reference must resolve to an artifact in the run, else it is flagged
    ungrounded (exit 1). The engine never calls a model — it emits the brief and ingests what Copilot
    wrote, and the narrative always renders as a needs-review advisory.
    """
    import json

    from sre_kb.render import load_kb
    from sre_kb.render.project import service_name
    from sre_kb.reporting import collect_findings, narrative_brief, render_narrative, validate_narrative
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    docs = load_kb(layout.root)
    found = collect_findings(docs)
    service = service_name(docs)

    if narrative is None:
        brief = narrative_brief(service, run_id, found, docs)
        if fmt == "text":
            typer.echo(brief["instruction"])
            typer.echo("\nallowed references:")
            for ref in brief["allowedRefs"]:
                typer.echo(f"  - {ref}")
        else:
            typer.echo(json.dumps(brief, indent=2))
        return

    text = narrative.read_text(encoding="utf-8")
    check = validate_narrative(text, found, docs)
    if fmt == "json":
        typer.echo(json.dumps({
            "service": service, "runId": run_id, "grounded": check.grounded,
            "citedRefs": check.cited_refs, "unknownRefs": check.unknown_refs, "note": check.note,
        }, indent=2))
    else:
        typer.echo(render_narrative(service, text, check))
    if not check.grounded:
        raise typer.Exit(code=1)  # a narrative citing an artifact not in the run is a defect


@app.command("scan-worklist")
def scan_worklist_cmd(
    run_id: str = typer.Option(..., "--run"),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Show the unified LLM scan worklist: every discover/confirm task Copilot should run for this
    run, with where to read each task's context and where to save its output. One front door for the
    manual LLM loop — the `sre-target-scan` agent reads this file and produces every output."""
    import json

    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    path = layout.root / "scan-worklist.json"
    if not path.exists():
        typer.echo("no scan worklist (run not validated yet)")
        raise typer.Exit(code=0)
    data = json.loads(path.read_text())
    for task in data["tasks"]:
        base = "<target>" if task["writeToBase"] == "target" else "<run>"
        typer.echo(f"  [{task['mode']}] {task['title']}")
        typer.echo(f"      skill:   {task['skill']}")
        typer.echo(f"      writeTo: {base}/{task['writeTo']}")
        typer.echo(f"      ingest:  {task['ingest']}")
    typer.echo(f"{len(data['tasks'])} task(s) for the LLM half — see {path}")
    typer.echo("run them in the IDE, or automate: sre-kb worklist-run --run "
               f"{run_id} --oracle '<llm-cli>'")


@app.command("worklist-run")
def worklist_run_cmd(
    run_id: str = typer.Option(..., "--run"),
    oracle: str = typer.Option(
        None,
        "--oracle",
        envvar="SRE_KB_ORACLE",
        help="External LLM-oracle command (e.g. 'copilot -p'). Prompt is fed on stdin. "
        "If unset, the worklist stays deferred to the manual IDE loop.",
    ),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-prompt oracle timeout (seconds)."),
    cache_dir: Path = typer.Option(None, "--cache-dir", help="Prompt-hash response cache dir (reproducibility)."),
    target: str = typer.Option(None, "--target", help="Scanned repo (default: from the worklist)."),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Drive the whole scan worklist (discover + confirm + challenge) through a programmatic LLM
    provider — the automated counterpart of the manual IDE file exchange.

    Each task's output lands in the exact file the manual loop would have written, so the same
    deterministic ingest gates re-ground everything: proposals on the next `sre-kb run`, verdicts
    via `challenge-apply` / `confirm-apply` (printed per task). The engine embeds no model; the
    provider is the operator-configured `--oracle` through the `LLMProvider` seam, and a provider
    can never assert a verdict the engine trusts.
    """
    import json

    from sre_kb.llm.provider import make_provider
    from sre_kb.pipeline.worklist_run import run_scan_worklist
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    wpath = layout.root / "scan-worklist.json"
    if not wpath.exists():
        typer.echo("no scan worklist (run not validated yet)")
        raise typer.Exit(code=0)
    worklist = json.loads(wpath.read_text())
    if not worklist["tasks"]:
        typer.echo("the scan worklist is empty — nothing for the LLM half to do")
        raise typer.Exit(code=0)
    if not oracle:
        typer.echo(
            "no --oracle configured (or SRE_KB_ORACLE unset): worklist deferred to the manual loop.\n"
            f"Run the tasks in the IDE (sre-kb scan-worklist --run {run_id}), or point --oracle at "
            "a Copilot/Claude CLI to run them end-to-end."
        )
        raise typer.Exit(code=0)

    tgt = Path(target or worklist["target"])
    cfg = {"llm": {"provider": "subprocess", "command": oracle, "timeout": timeout,
                   **({"cache_dir": str(cache_dir)} if cache_dir else {})}}
    client = make_provider(cfg)
    summaries = run_scan_worklist(layout, worklist, client, target=tgt)
    for s in summaries:
        line = f"  [{s['status']}] {s['task']}: {s['note']}"
        if s.get("output"):
            line += f" → {s['output']}"
        typer.echo(line)
    ingests = [s["ingest"] for s in summaries if s["status"] == "written"]
    if ingests:
        typer.echo("ingest (deterministic, re-grounds every output):")
        for cmd in ingests:
            typer.echo(f"  {cmd}")


@app.command()
def autopilot(
    target: str = typer.Option(..., "--target", help="Local path of the target repo."),
    oracle: str = typer.Option(
        None,
        "--oracle",
        envvar="SRE_KB_ORACLE",
        help="External LLM-oracle command (e.g. 'copilot -p'). Prompt is fed on stdin. "
        "Required — without a provider the loop is the manual IDE exchange.",
    ),
    cycles: int = typer.Option(2, "--cycles", help="Convergence cycles (scan → provider → apply)."),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-prompt oracle timeout (seconds)."),
    cache_dir: Path = typer.Option(None, "--cache-dir", help="Prompt-hash response cache dir (reproducibility)."),
    run_id: str = typer.Option(None, "--run", help="Base run id (cycles get -c1, -c2, …)."),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Converge the whole LLM loop in one command: scan → worklist through the provider → apply →
    re-scan (the SCOPE §6 discover→re-ground cycle, default 2 cycles), then fold the surviving
    Tier-B drafts into the final run's KB.

    The trust boundary is unchanged from the manual loop: verdicts apply monotonically
    (downgrade-only), proposals are re-grounded byte-by-byte on the next scan, and drafts land
    `needs-review` — a provider can never assert a verdict the engine trusts. The engine embeds no
    model; `--cache-dir` makes re-runs replay deterministically.
    """
    from sre_kb.llm.provider import make_provider
    from sre_kb.pipeline.autopilot import run_autopilot
    from sre_kb.workspace import RunLayout

    if not oracle:
        typer.echo(
            "no --oracle configured (or SRE_KB_ORACLE unset): autopilot needs a programmatic "
            "provider.\nUse the manual loop instead (sre-kb run, then sre-kb scan-worklist), or "
            "point --oracle at a Copilot/Claude CLI."
        )
        raise typer.Exit(code=0)
    cfg = {"llm": {"provider": "subprocess", "command": oracle, "timeout": timeout,
                   **({"cache_dir": str(cache_dir)} if cache_dir else {})}}
    client = make_provider(cfg)
    result = run_autopilot(target, client, work_root=work_root, run_base=run_id, cycles=cycles)
    for i, cycle in enumerate(result.cycles, 1):
        typer.echo(f"cycle {i} — run {cycle.run_id}")
        if not cycle.tasks:
            typer.echo("  no LLM work — converged")
            continue
        for t in cycle.tasks:
            typer.echo(f"  [{t['status']}] {t['task']}: {t['note']}")
        typer.echo(f"  applied: {cycle.challenge_changed} challenge downgrade(s), "
                   f"{cycle.confirm_outcomes} boundary call(s) re-ground")
    typer.echo(f"drafts folded into the final run: {result.drafted_alerts} alert(s), "
               f"{result.drafted_runbooks} runbook(s), {result.contract_routed} contract break(s) "
               "routed to review")
    if result.narrative_note:
        typer.echo(f"narrative: {result.narrative_note}")
    final = RunLayout(Path(work_root), result.run_id)
    typer.echo(f"converged KB: {final.kb}  (render/publish: sre-kb render --run {result.run_id})")


@app.command("challenge-worklist")
def challenge_worklist(
    run_id: str = typer.Option(..., "--run"),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Show the LLM challenge worklist (judgment-call claims for Copilot to adjudicate)."""
    import json

    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    path = layout.root / "challenge" / "worklist.json"
    if not path.exists():
        typer.echo("no worklist (no review claims, or run not validated yet)")
        raise typer.Exit(code=0)
    data = json.loads(path.read_text())
    for item in data["items"]:
        typer.echo(f"  {item['artifact']}  [{item['claimId']}]")
    typer.echo(f"{len(data['items'])} claim(s) for review — see {path}")


@app.command("challenge-run")
def challenge_run(
    run_id: str = typer.Option(..., "--run"),
    oracle: str = typer.Option(
        None,
        "--oracle",
        envvar="SRE_KB_ORACLE",
        help="External LLM-oracle command (e.g. 'copilot -p'). Prompt is fed on stdin. "
        "If unset, the loop stays deferred (no verdicts written) — same as offline.",
    ),
    timeout: float = typer.Option(120.0, "--timeout", help="Per-claim oracle timeout (seconds)."),
    cache_dir: Path = typer.Option(None, "--cache-dir", help="Prompt-hash response cache dir (reproducibility)."),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Drive the challenge worklist through a programmatic LLM provider and write verdicts.

    The provider is built through the `LLMProvider` seam (`llm/provider.py`). The engine embeds no
    model — the default is the model-free Copilot file exchange; `--oracle` selects the subprocess
    provider (the Copilot/Claude CLI), and `--cache-dir` wraps it in a prompt-hash cache for
    reproducibility. With no oracle the loop defers to a human. Verdicts only ever downgrade via
    `challenge-apply`; a provider can never raise confidence. Then run `sre-kb challenge-apply`.
    """
    import json

    from sre_kb.llm.provider import make_provider
    from sre_kb.pipeline.challenge_run import run_worklist
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    wpath = layout.root / "challenge" / "worklist.json"
    if not wpath.exists():
        typer.echo("no worklist (no review claims, or run not validated yet)")
        raise typer.Exit(code=0)
    if not oracle:
        typer.echo(
            "no --oracle configured (or SRE_KB_ORACLE unset): loop deferred to a human.\n"
            "Point --oracle at a Copilot/Claude CLI to adjudicate end-to-end, or write "
            f"{layout.root / 'challenge' / 'verdicts.json'} by hand."
        )
        raise typer.Exit(code=0)

    worklist = json.loads(wpath.read_text())
    cfg = {"llm": {"provider": "subprocess", "command": oracle, "timeout": timeout,
                   **({"cache_dir": str(cache_dir)} if cache_dir else {})}}
    client = make_provider(cfg)
    result = run_worklist(worklist, client, oracle_id=client.id)
    vpath = layout.root / "challenge" / "verdicts.json"
    vpath.write_text(json.dumps(result, indent=2), encoding="utf-8")
    by_verdict: dict[str, int] = {}
    for v in result["verdicts"]:
        by_verdict[v["verdict"]] = by_verdict.get(v["verdict"], 0) + 1
    for verdict in ("contradicted", "unsupported", "indeterminate", "supported"):
        if by_verdict.get(verdict):
            typer.echo(f"  {verdict}: {by_verdict[verdict]}")
    typer.echo(f"wrote {len(result['verdicts'])} verdict(s) → {vpath}  (now: sre-kb challenge-apply --run {run_id})")


@app.command("challenge-apply")
def challenge_apply(
    run_id: str = typer.Option(..., "--run"),
    verdicts: Path = typer.Option(None, "--verdicts", help="Verdicts JSON (default: <run>/challenge/verdicts.json)."),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Apply Copilot's challenge verdicts and re-gate artifacts (monotonic downgrade-only)."""
    import json

    from sre_kb.pipeline.challenge_apply import apply_verdicts
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    vpath = verdicts or (layout.root / "challenge" / "verdicts.json")
    if not vpath.exists():
        typer.echo(f"no verdicts file at {vpath}", err=True)
        raise typer.Exit(code=1)
    summary = apply_verdicts(layout, json.loads(vpath.read_text()))
    for s in summary:
        if s.get("result") == "not-found":
            typer.echo(f"  {s['artifact']}: not found")
        else:
            change = f"→ {s['new']}" if s["new"] != s["old"] else "(unchanged)"
            typer.echo(f"  {s['artifact']}: {s['old']} {change}")
    typer.echo(f"applied verdicts to {len(summary)} artifact(s).")


@app.command("confirm-worklist")
def confirm_worklist_cmd(
    run_id: str = typer.Option(..., "--run"),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Show the S4 confirm worklist: the engine's Tier-A boundary calls for Copilot to affirm or
    dispute with a verbatim anchor — absence ("present here") and presence ("disabled here"). The
    engine re-grounds each dispute via `confirm-apply`."""
    import json

    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    path = layout.root / "confirm" / "boundary-calls.json"
    if not path.exists():
        typer.echo("no confirm worklist (no Tier-A absence claims, or run not validated yet)")
        raise typer.Exit(code=0)
    data = json.loads(path.read_text())
    for item in data["items"]:
        verb = "active" if item.get("direction") == "presence" else "absent"
        typer.echo(f"  {item['artifact']}  [{item['claimId']}]  "
                   f"{verb}: {' / '.join(item['concern'])} @ {item['path']}:{item['line']}")
    n_pres = sum(1 for i in data["items"] if i.get("direction") == "presence")
    typer.echo(f"{len(data['items'])} boundary call(s) to confirm "
               f"({len(data['items']) - n_pres} absence, {n_pres} presence) — see {path}")


@app.command("confirm-apply")
def confirm_apply_cmd(
    run_id: str = typer.Option(..., "--run"),
    verdicts: Path = typer.Option(None, "--verdicts", help="Verdicts JSON (default: <run>/confirm/verdicts.json)."),
    target: str = typer.Option(None, "--target", help="Scanned repo to re-ground against (default: from the run report)."),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Apply confirm verdicts: re-ground each dispute. An absence dispute that re-derives drops a
    false-positive gap (→ rejected); a presence dispute that re-derives a disable emits a new Tier-A
    disabled-resilience gap. The engine makes every deterministic call."""
    import json

    from sre_kb.pipeline.confirm import regate_run
    from sre_kb.workspace import RunLayout

    layout = RunLayout(Path(work_root), run_id)
    vpath = verdicts or (layout.root / "confirm" / "verdicts.json")
    if not vpath.exists():
        typer.echo(f"no verdicts file at {vpath}", err=True)
        raise typer.Exit(code=1)
    tgt = target
    if tgt is None:
        report = layout.reports / "validation_report.json"
        if report.exists():
            tgt = json.loads(report.read_text()).get("target")
    if not tgt:
        typer.echo("no target to re-ground against (pass --target)", err=True)
        raise typer.Exit(code=1)
    verdict_doc = json.loads(vpath.read_text())
    outcomes = regate_run(layout, tgt, verdict_doc)
    for o in outcomes:
        typer.echo(f"  {o.artifact}: {o.result}  ({o.note})")
    refuted = sum(1 for o in outcomes if o.result == "refuted")
    disabled = sum(1 for o in outcomes if o.result == "disabled-confirmed")
    typer.echo(f"confirmed {len(outcomes)} claim(s); {refuted} absence gap(s) → rejected, "
               f"{disabled} present-but-disabled gap(s) emitted.")
    # Graduation-from-confirms: feed these verdicts into the target's graduation tally, so confirms
    # accrue toward promoting a deterministic rule exactly as `confirm-gap` does for the discover loop.
    from sre_kb.pipeline.confirm import record_confirm_graduation

    recorded = record_confirm_graduation(Path(tgt), outcomes, run_id)
    for cat, verdict in sorted(recorded.items()):
        typer.echo(f"  graduation: recorded {verdict} for {cat}")


@app.command("gap-finder")
def gap_finder_cmd(
    target: str = typer.Option(..., "--target", help="Local path of the target repo."),
    proposals: Path = typer.Option(
        None, "--proposals", help="LLM gap proposals JSON (default: <target>/.sre/gap-proposals.json)."
    ),
    service: str = typer.Option(None, "--service", help="Service name (default: target dir name)."),
) -> None:
    """Tier-B LLM gap-finder (HYBRID-PLAN §7.9): ingest Copilot's gap proposals, re-ground each
    (locate -> stamp path:line:hash source_tier=llm -> re-derive via the signature library), and
    emit ResiliencyGap artifacts.

    The engine never calls a model — it ingests proposals Copilot already wrote by running the
    sre-gap-finder (assess-resiliency) skill. Nothing proposed can auto-verify.
    """
    from sre_kb.pipeline.gap_finder import run_gap_finder

    run = run_gap_finder(target, proposals_path=proposals, service=service)
    kept, conf = run.result.kept(), run.result.confirmed()
    routed = len(kept) - len(conf)
    typer.echo(
        f"gap-finder: {len(run.result.outcomes)} proposal(s) -> {len(kept)} kept "
        f"({len(conf)} confirmed + {routed} routed), {len(run.result.dropped())} dropped"
    )
    for o in run.result.outcomes:
        where = f" @ {o.path}:{o.lines[0]}-{o.lines[1]}" if o.lines else ""
        typer.echo(f"  [{o.result:<12}] {o.proposal.category} on {o.proposal.target}{where}  — {o.note}")
    for status, n in sorted(run.by_status.items()):
        typer.echo(f"  {status}: {n}")


@app.command("map-contracts")
def map_contracts_cmd(
    target: str = typer.Option(..., "--target", help="Local path of the target repo."),
    proposals: Path = typer.Option(
        None, "--proposals",
        help="Semantic-break proposals JSON (default: <target>/.sre/contract-proposals.json)."
    ),
    report: Path = typer.Option(None, "--report", help="Write the re-grounding report JSON here."),
) -> None:
    """Tier-B map-api-contracts (coverage #7): ingest the skill's semantic-break proposals and
    re-ground each — locate the anchor in the current spec, drop anything the deterministic baseline
    diff already covers as a structural change, and route genuine semantic breaks to review.

    The engine never calls a model — it ingests proposals Copilot already wrote by running the
    map-api-contracts skill. Nothing proposed can auto-verify.
    """
    from sre_kb.pipeline.contract import run_map_contracts

    result = run_map_contracts(target, proposals_path=proposals)
    kept, dropped = result.kept(), result.dropped()
    typer.echo(
        f"map-contracts: {len(result.outcomes)} proposal(s) -> {len(kept)} routed to review, "
        f"{len(dropped)} dropped"
    )
    for o in result.outcomes:
        where = f" @ {o.path}:{o.lines[0]}-{o.lines[1]}" if o.lines else ""
        typer.echo(f"  [{o.result:<11}] {o.proposal.target}{where}  — {o.note}")
    if report is not None:
        payload = [
            {"target": o.proposal.target, "category": o.proposal.category, "result": o.result,
             "path": o.path, "lines": list(o.lines) if o.lines else None,
             "severity": o.proposal.severity, "rationale": o.proposal.rationale, "note": o.note}
            for o in result.outcomes
        ]
        report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        typer.echo(f"  report -> {report}")


@app.command("generate-alerts")
def generate_alerts_cmd(
    target: str = typer.Option(..., "--target", help="Local path of the target repo."),
    proposals: Path = typer.Option(
        None, "--proposals",
        help="Alert-worthiness proposals JSON (default: <target>/.sre/alert-proposals.json)."
    ),
    service: str = typer.Option(None, "--service", help="Service name (default: target dir name)."),
    report: Path = typer.Option(None, "--report", help="Write the re-grounding report JSON here."),
) -> None:
    """Tier-B generate-alerts (coverage #19): ingest the skill's alert-worthiness proposals and
    re-ground each — locate the cited log line, confirm a parsed log statement at error/warn level
    (refuting info/debug), derive the search query from the byte-grounded message, and render a
    needs-review log-pattern Alert. Nothing proposed can auto-verify; the engine never calls a model.
    """
    from sre_kb.pipeline.alerts_draft import run_generate_alerts

    result = run_generate_alerts(target, proposals_path=proposals, service=service)
    kept, dropped = result.kept(), result.dropped()
    typer.echo(
        f"generate-alerts: {len(result.outcomes)} proposal(s) -> {len(kept)} drafted "
        f"(needs-review), {len(dropped)} dropped"
    )
    for o in result.outcomes:
        where = f" @ {o.path}:{o.line}" if o.line else ""
        typer.echo(f"  [{o.result:<12}]{where}  — {o.note}")
    if report is not None:
        payload = [
            {"result": o.result, "path": o.path, "line": o.line,
             "severity": o.proposal.severity, "rationale": o.proposal.rationale, "note": o.note}
            for o in result.outcomes
        ]
        report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        typer.echo(f"  report -> {report}")


@app.command("generate-runbooks")
def generate_runbooks_cmd(
    target: str = typer.Option(..., "--target", help="Local path of the target repo."),
    proposals: Path = typer.Option(
        None, "--proposals",
        help="Runbook proposals JSON (default: <target>/.sre/runbook-proposals.json)."
    ),
    service: str = typer.Option(None, "--service", help="Service name (default: target dir name)."),
    report: Path = typer.Option(None, "--report", help="Write the re-grounding report JSON here."),
) -> None:
    """Tier-B generate-runbooks (coverage #20): ingest the skill's drafted runbooks and re-ground each
    — the trigger Alert must resolve to a real run artifact (an Alert that already has a runbook is
    refused), and every Kind/name reference in the prose is grounded against the run's artifacts.
    Survivors scaffold as needs-review Runbook artifacts. The engine never calls a model.
    """
    from sre_kb.pipeline.runbooks_draft import run_generate_runbooks

    result = run_generate_runbooks(target, proposals_path=proposals, service=service)
    kept, dropped = result.kept(), result.dropped()
    typer.echo(
        f"generate-runbooks: {len(result.outcomes)} proposal(s) -> {len(kept)} drafted "
        f"(needs-review), {len(dropped)} dropped"
    )
    for o in result.outcomes:
        flagged = f"  [ungrounded: {', '.join(o.ungrounded_refs)}]" if o.ungrounded_refs else ""
        typer.echo(f"  [{o.result:<17}] {o.proposal.alert_ref}  — {o.note}{flagged}")
    if report is not None:
        payload = [
            {"alertRef": o.proposal.alert_ref, "result": o.result,
             "ungroundedRefs": list(o.ungrounded_refs), "note": o.note}
            for o in result.outcomes
        ]
        report.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        typer.echo(f"  report -> {report}")


@app.command("copilot-gap-validate")
def copilot_gap_validate_cmd(
    target: str = typer.Option(..., "--target", help="Local path of the target repo."),
    truth: Path = typer.Option(..., "--truth", help="Expected gap truth set JSON."),
    proposals: Path = typer.Option(
        None,
        "--proposals",
        help="Real Copilot proposals JSON (default: <target>/.sre/gap-proposals.json).",
    ),
    service: str = typer.Option(None, "--service", help="Service name (default: target dir name)."),
    min_recall: float = typer.Option(1.0, "--min-recall", help="Minimum kept recall required."),
    min_kept_precision: float = typer.Option(
        1.0, "--min-kept-precision", help="Minimum post-grounding precision required."
    ),
    report: Path = typer.Option(None, "--report", help="Optional JSON report path."),
) -> None:
    """Validate a saved real-Copilot gap-finder run against a truth set.

    This does not invoke Copilot. Run Copilot in VS Code with the sre-gap-finder skill first,
    save `.sre/gap-proposals.json`, then use this command to measure raw proposals and
    post-grounding quality.
    """
    import json

    from sre_kb.validation.copilot_gap import validate_copilot_gap_run

    try:
        result = validate_copilot_gap_run(
            target, truth_path=truth, proposals_path=proposals, service=service
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    def fmt(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    typer.echo(f"copilot-gap-validate: {result.proposals_path}")
    typer.echo(
        f"  expected={len(result.expected)} proposed={len(result.proposed)} "
        f"grounded={len(result.grounded)} kept={len(result.kept)} confirmed={len(result.confirmed)}"
    )
    typer.echo(
        f"  proposal-recall={fmt(result.proposal_recall)} kept-recall={fmt(result.kept_recall)} "
        f"proposal-precision={fmt(result.proposal_precision)} "
        f"kept-precision={fmt(result.kept_precision)} grounded-rate={fmt(result.grounded_rate)}"
    )
    if result.missed_expected:
        typer.echo(f"  missed: {sorted(result.missed_expected)}")
    if result.false_positive_kept:
        typer.echo(f"  false-positive kept: {sorted(result.false_positive_kept)}")
    if result.controls_proposed:
        typer.echo(f"  controls proposed: {sorted(result.controls_proposed)}")
    if result.controls_kept:
        typer.echo(f"  controls kept: {sorted(result.controls_kept)}")

    payload = result.as_dict()
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"  report: {report}")

    ok = result.passes(min_recall=min_recall, min_kept_precision=min_kept_precision)
    raise typer.Exit(code=0 if ok else 1)


@app.command("secret-scan")
def secret_scan(directory: Path = typer.Argument(..., help="Directory to scan for secrets.")) -> None:
    """Scan a directory tree for secrets (the publish gate uses the same rules)."""
    from sre_kb.security import scan_tree

    findings = scan_tree(directory)
    for f in findings:
        typer.echo(f"{f['rule']}  {f['path']}:{f['line']}")
    typer.echo(f"{len(findings)} secret(s) found.")
    raise typer.Exit(code=1 if findings else 0)


@app.command()
def estate(
    target: list[str] = typer.Option(..., "--target", help="Repeatable: each service repo path."),
    work_root: str = typer.Option(".work", "--work-root"),
    run_id: str = typer.Option(None, "--run"),
) -> None:
    """Build an estate-level Topology + co-tenancy blast radius across services."""
    from sre_kb.estate import run_estate

    r = run_estate(list(target), work_root=work_root, run_id=run_id)
    typer.echo(f"estate {r.run_id}: {len(r.services)} services {r.services}, {r.docs} artifact(s)")
    for status, n in sorted(r.by_status.items()):
        typer.echo(f"  {status}: {n}")
    typer.echo(f"  output: {r.root}")


@app.command()
def diff(
    from_target: str = typer.Option(..., "--from", help="Base target repo path (older)."),
    to_target: str = typer.Option(..., "--to", help="Head target repo path (newer)."),
    work_root: str = typer.Option(".work", "--work-root"),
) -> None:
    """Drift detection: scan two versions of a repo and diff the resulting KB."""
    from sre_kb.drift import changelog_md, diff_kb
    from sre_kb.pipeline import run as run_pipeline
    from sre_kb.render import load_kb

    base = run_pipeline(from_target, work_root=work_root, run_id="diff-base", to_stage="validate")
    head = run_pipeline(to_target, work_root=work_root, run_id="diff-head", to_stage="validate")
    d = diff_kb(load_kb(base.root), load_kb(head.root))
    drift_dir = head.root / "drift"
    drift_dir.mkdir(exist_ok=True)
    changelog = drift_dir / "CHANGELOG.md"
    changelog.write_text(changelog_md(d, from_target, to_target), encoding="utf-8")
    typer.echo(
        f"drift: +{len(d.added)} -{len(d.removed)} ~{len(d.changed)} "
        f"data-loss+{len(d.new_data_loss)}"
    )
    if d.new_data_loss:
        for k in d.new_data_loss:
            typer.echo(f"  ⚠️ new data-loss risk: {k[0]}/{k[1]}")
    typer.echo(f"  changelog: {changelog}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
