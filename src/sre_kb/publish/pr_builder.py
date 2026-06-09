"""Assemble the per-service PR tree (Backstage-style) under <run>/pr/ and, unless
--dry-run, hand it to a Forge. A REVIEW.md surfaces everything not auto-verified."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from sre_kb import __version__
from sre_kb.config import load_config, schemas_dir
from sre_kb.publish.forge import ForgePublishError, get_forge
from sre_kb.render.project import load_kb, render_projections, service_name
from sre_kb.tiers import tier_label
from sre_kb.workspace import RunLayout


def _review_md(docs: list[dict], report: dict | None) -> str:
    rep = report or {}
    by_status = rep.get("by_status", {})
    by_tier = rep.get("by_tier", {})
    lines = ["# SRE KB — review summary", "", f"- artifacts: {len(docs)}"]
    lines += [f"- {k}: {by_status[k]}" for k in sorted(by_status)]
    if by_tier:
        lines.append("- trust: " + ", ".join(f"{tier_label(k)} {by_tier[k]}" for k in sorted(by_tier)))
    lines += ["", "## Needs review / not auto-verified", ""]
    any_nr = False
    for r in rep.get("records", []):
        if r.get("status") != "verified":
            any_nr = True
            reasons = [k for k in ("structural", "provenance", "crossref") if r.get(k)]
            extra = f" ({', '.join(reasons)})" if reasons else ""
            lines.append(f"- [ ] {r['artifact']} → {r['status']} [{tier_label(r.get('tier', 'ast'))}]{extra}")
    if not any_nr:
        lines.append("- (all verified)")
    return "\n".join(lines) + "\n"


def _pr_title(service: str) -> str:
    """Single-line, length-bounded PR/commit title — an unconstrained service name can't inject a
    newline into the commit subject or forge a misleading second line."""
    return "SRE KB: " + re.sub(r"\s+", " ", service).strip()[:100]


def _claim_file(produced: dict[str, Path], src: Path, rel: Path) -> None:
    key = rel.as_posix()
    if key in produced:
        raise ForgePublishError(f"output name collision: {key}")
    produced[key] = src


def _claim_tree(produced: dict[str, Path], src_root: Path, dest_rel: Path) -> None:
    if not src_root.exists():
        return
    for src in sorted(src_root.rglob("*")):
        if src.is_file():
            _claim_file(produced, src, dest_rel / src.relative_to(src_root))


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_tree(src: Path, dest: Path) -> None:
    if src.exists():
        shutil.copytree(src, dest, dirs_exist_ok=True)


def _generated_validate_workflow(pip_args: str = "") -> str:
    return f"""name: validate-sre-kb

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          persist-credentials: false  # validate-only job; no token left in .git/config
      - name: Require CODEOWNERS team
        run: |
          if grep -q 'REPLACE_ME__owning_team' .github/CODEOWNERS; then
            echo "::error::Replace REPLACE_ME__owning_team and enable Code Owner review."
            exit 1
          fi
      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"  # matches the engine's requires-python floor
      - name: Install pinned engine
        run: python -m pip install {pip_args}"$(cat .sre/version)"
      - name: Validate KB artifacts
        run: |
          shopt -s nullglob
          found=0
          for kb in catalog/*/kb; do
            sre-kb validate-kb --schema-dir .sre/schemas "$kb"
            found=1
          done
          [ "$found" = 1 ] || {{ echo "::error::no catalog/*/kb directories found"; exit 1; }}
      - name: Fail-closed secret gate
        run: sre-kb secret-scan .
"""


def _generated_pr_template() -> str:
    return """# SRE KB update

This repository contains AI-assisted SRE knowledge-base output. Review every changed artifact before
merge.

- [ ] Replace any `REPLACE_ME__` sentinels or leave a tracked follow-up.
- [ ] Review all `needs-review` artifacts in `REVIEW.md`.
- [ ] Confirm generated alerts, dashboards, and runbooks against live systems before enabling them.
- [ ] Confirm CODEOWNERS and branch protection are configured for this repo.
- [ ] Confirm the pinned engine in `.sre/version` is installable from this repo's CI
      (`publish.engine_index_url` / an internal index) — the validate workflow fails without it.
"""


def _generated_editor_settings() -> str:
    """yaml-language-server mapping (VS Code YAML extension): every KB artifact validates inline
    against the repo's OWN vendored schemas while a reviewer reads it — the review loop gets
    schema validation for free, pinned to the exact schema version the artifacts were written
    against (not whatever the engine ships today)."""
    import json

    from sre_kb.registry import kinds, schema_for

    mapping = {
        f".sre/{schema_for(kind)}": f"catalog/*/kb/**/{kind}/*.yaml"
        for kind in sorted(kinds())
        if schema_for(kind)
    }
    return json.dumps({"yaml.schemas": mapping}, indent=2, sort_keys=True) + "\n"


def _stage_repo_root_hardening(pr_root: Path, publish_cfg: dict | None = None) -> None:
    """Stage repo-control files at the *published repo root*. GitHub honors workflows, CODEOWNERS,
    and the PR template only at the root (or root ``.github/``), never under ``catalog/<service>/`` —
    so these must sit beside the catalog, not inside it. The vendored schemas + pinned engine version
    let the generated CI validate the KB hermetically.

    The engine is NOT on public PyPI: the generated workflow installs `publish.engine_spec`
    (default ``sre-kb==<this version>``) from `publish.engine_index_url` — configure one (internal
    index, or an engine_spec pointing at a wheel URL) before the first real publish, or the
    generated CI fails on its install step."""
    cfg = publish_cfg or {}
    engine_spec = cfg.get("engine_spec") or f"sre-kb=={__version__}"
    index_url = cfg.get("engine_index_url")
    pip_args = f"--index-url {index_url} " if index_url else ""
    _copy_tree(schemas_dir(), pr_root / ".sre" / "schemas")
    _write_file(pr_root / ".sre" / "version", f"{engine_spec}\n")
    _write_file(pr_root / ".github" / "CODEOWNERS", "* REPLACE_ME__owning_team\n")
    _write_file(pr_root / ".github" / "workflows" / "validate-sre-kb.yml",
                _generated_validate_workflow(pip_args))
    _write_file(pr_root / ".github" / "pull_request_template.md", _generated_pr_template())
    _write_file(pr_root / ".vscode" / "settings.json", _generated_editor_settings())


def _stage_pr_tree(stage: Path, layout: RunLayout, proj: Path, service: str, docs: list[dict], report: dict | None) -> None:
    produced: dict[str, Path] = {}

    _claim_tree(produced, layout.kb, Path("kb"))
    _claim_tree(produced, proj / ".github", Path(".github"))
    _claim_tree(produced, proj / "runbooks", Path("runbooks"))
    _claim_tree(produced, proj / "diagrams", Path("diagrams"))
    _claim_file(produced, proj / "catalog-info.yaml", Path("catalog-info.yaml"))

    review = stage / "_generated" / "REVIEW.md"
    review.parent.mkdir(parents=True, exist_ok=True)
    review.write_text(_review_md(docs, report), encoding="utf-8")
    _claim_file(produced, review, Path("REVIEW.md"))

    from sre_kb.reporting import collect_findings, render_md

    findings = stage / "_generated" / "FINDINGS.md"
    findings.write_text(render_md(service, layout.run_id, collect_findings(docs), docs), encoding="utf-8")
    _claim_file(produced, findings, Path("FINDINGS.md"))

    for rel, src in produced.items():
        dest = stage / "tree" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def assemble_pr(
    layout: RunLayout,
    docs: list[dict] | None = None,
    report: dict | None = None,
    *,
    sre_repo: str = "(unset)",
    branch: str = "sre-kb/update",
    forge: str = "github",
    dry_run: bool = True,
    allow_secrets: bool = False,
    allowed_repos: list[str] | None = None,
    max_artifacts: int | None = None,
) -> tuple[Path, str]:
    docs = docs if docs is not None else load_kb(layout.root)
    cap = max_artifacts if max_artifacts is not None else (load_config().get("publish") or {}).get("max_artifacts")
    if cap is not None and len(docs) > cap:
        raise ForgePublishError(
            f"fan-out cap exceeded: {len(docs)} artifacts exceed publish.max_artifacts={cap} "
            f"— a runaway/compromised scan must not flood a target repo"
        )
    proj = layout.root / "projections"
    if not proj.exists():
        render_projections(layout, docs)

    service = service_name(docs)
    pr_root = layout.root / "pr"
    base = pr_root / "catalog" / service
    # Containment: `service` is not schema-pattern-constrained, so guard against a name like
    # `../../x` letting the staged path escape the catalog before we ever write to disk.
    if not base.resolve().is_relative_to((pr_root / "catalog").resolve()):
        raise ForgePublishError(f"unsafe service name for publish path: {service!r}")
    # Clean re-stage so a prior run's files never linger to be re-scanned or re-published. Operator
    # edits live in the published *target* repo (preserved by the forge's manifest merge), never in
    # this throwaway staging dir — so rebuilding it from scratch each run is correct.
    if pr_root.exists():
        shutil.rmtree(pr_root)
    base.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sre-kb-pr-") as tmp:
        stage = Path(tmp)
        _stage_pr_tree(stage, layout, proj, service, docs, report)
        shutil.copytree(stage / "tree", base, dirs_exist_ok=True)
    # Repo-control files belong at the published repo root, not under catalog/<service>/.
    _stage_repo_root_hardening(pr_root, load_config().get("publish") or {})

    tree = pr_root
    # Fail closed before publish: generated output containing a real secret is surfaced for human
    # review, not silently scrubbed. Vendored schemas are first-party assets, so they're skipped —
    # a schema's example value must not be able to wedge every publish.
    from sre_kb.security import enforce_secret_gate, redact_tree

    findings = enforce_secret_gate(tree, allow=allow_secrets, skip_prefixes=(".sre/schemas", ".git"))
    if findings and allow_secrets:
        # Explicit operator override: redact detected secrets rather than publish them raw, then
        # re-gate. If anything survives redaction (e.g. a future detector with no redactor), fail
        # closed — block the publish rather than leak a residual secret.
        redact_tree(tree, skip_prefixes=(".sre/schemas", ".git"))
        enforce_secret_gate(tree, skip_prefixes=(".sre/schemas", ".git"))
    if dry_run:
        return tree, f"dry-run: staged PR tree at {tree} (would target {sre_repo})"
    ref = get_forge(forge, allowed_repos=allowed_repos).open_pr(
        tree, sre_repo=sre_repo, branch=branch, title=_pr_title(service), body=_review_md(docs, report)
    )
    return tree, ref
