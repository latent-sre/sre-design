"""`sre-kb` command-line interface.

Phase 0 wires the full command surface. `schema` and `validate-kb` are functional;
the pipeline stages (run/scan/validate/render/publish/diff) are phase-aware stubs that
will be filled in with the P1 slice. The engine never calls an LLM — enrichment happens
in VS Code via Copilot between `scan` and `validate`.
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

_NOT_YET = "Not implemented yet — lands with the {phase} build (see docs/DESIGN.md)."


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


def _stub(name: str, phase: str) -> None:
    typer.echo(f"`sre-kb {name}`: {_NOT_YET.format(phase=phase)}")
    raise typer.Exit(code=0)


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
def render(run_id: str = typer.Option(..., "--run")) -> None:
    """Render the Copilot projection + Backstage catalog from the validated KB."""
    _stub("render", "P1")


@app.command()
def publish(
    run_id: str = typer.Option(..., "--run"),
    sre_repo: str = typer.Option(..., "--sre-repo"),
    forge: str = typer.Option("github", "--forge"),
    dry_run: bool = typer.Option(True, "--dry-run/--no-dry-run"),
) -> None:
    """Stage the per-service tree and (optionally) open the PR. Defaults to --dry-run."""
    _stub("publish", "P1")


@app.command()
def diff(
    from_commit: str = typer.Option(..., "--from"),
    to_commit: str = typer.Option(..., "--to"),
) -> None:
    """Drift detection: diff the KB across two scanned commits."""
    _stub("diff", "P2")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
