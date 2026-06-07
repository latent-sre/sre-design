"""`sre-kb` command-line interface.

All subcommands are implemented: `run`/`scan`/`render`/`publish` (the deterministic pipeline),
`validate-kb`, `findings`, `estate`, `diff`, `challenge-worklist`/`challenge-apply`,
`gap-finder`, `secret-scan`, and `schema`. There is no separate `validate` subcommand — validation is the
default `--to-stage` of `run`. The engine never calls an LLM — enrichment happens in VS Code via
Copilot between `scan` and the validate stage, and the LLM challenge oracle runs out-of-process
(worklist → Copilot → `challenge-apply`).
"""

from __future__ import annotations

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
def validate_kb(directory: Path = typer.Argument(..., help="Directory of KB YAML artifacts.")) -> None:
    """Validate an existing KB tree against the schemas. Exits non-zero on any failure."""
    if not directory.exists():
        typer.echo(f"no such directory: {directory}", err=True)
        raise typer.Exit(code=2)
    results = validate_kb_tree(directory)
    failures = [r for r in results if not r.ok]
    for r in results:
        mark = "ok  " if r.ok else "FAIL"
        typer.echo(f"[{mark}] {r.path} ({r.kind or '?'})")
        for err in r.errors:
            typer.echo(f"         - {err}")
    typer.echo(f"\n{len(results)} artifact(s), {len(failures)} failed.")
    raise typer.Exit(code=1 if failures else 0)


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
