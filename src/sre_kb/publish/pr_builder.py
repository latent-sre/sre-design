"""Assemble the per-service PR tree (Backstage-style) under <run>/pr/ and, unless
--dry-run, hand it to a Forge. A REVIEW.md surfaces everything not auto-verified."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sre_kb import __version__
from sre_kb.config import load_config
from sre_kb.publish.forge import ForgePublishError, get_forge
from sre_kb.publish.manifest import merge_tree
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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _write_generated_file(produced: dict[str, Path], stage: Path, rel: Path, content: str) -> None:
    path = stage / "_generated" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _claim_file(produced, path, rel)


def _generated_validate_workflow() -> str:
    return """name: validate-sre-kb

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
      - uses: actions/checkout@v4
      - name: Require CODEOWNERS team
        run: |
          if grep -q 'REPLACE_ME__owning_team' .github/CODEOWNERS; then
            echo "::error::Replace REPLACE_ME__owning_team and enable Code Owner review."
            exit 1
          fi
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install pinned engine
        run: python -m pip install "$(cat .sre/version)"
      - name: Validate KB artifacts
        run: sre-kb validate-kb --schema-dir .sre/schemas kb
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
"""


def _claim_generated_repo_hardening(produced: dict[str, Path], stage: Path) -> None:
    _claim_tree(produced, _repo_root() / "schemas", Path(".sre/schemas"))
    _write_generated_file(produced, stage, Path(".sre/version"), f"sre-kb=={__version__}\n")
    _write_generated_file(produced, stage, Path(".github/CODEOWNERS"), "* REPLACE_ME__owning_team\n")
    _write_generated_file(
        produced,
        stage,
        Path(".github/workflows/validate-sre-kb.yml"),
        _generated_validate_workflow(),
    )
    _write_generated_file(
        produced,
        stage,
        Path(".github/pull_request_template.md"),
        _generated_pr_template(),
    )


def _stage_pr_tree(stage: Path, layout: RunLayout, proj: Path, service: str, docs: list[dict], report: dict | None) -> None:
    produced: dict[str, Path] = {}

    _claim_tree(produced, layout.kb, Path("kb"))
    _claim_tree(produced, proj / ".github", Path(".github"))
    _claim_tree(produced, proj / "runbooks", Path("runbooks"))
    _claim_tree(produced, proj / "diagrams", Path("diagrams"))
    _claim_file(produced, proj / "catalog-info.yaml", Path("catalog-info.yaml"))
    _claim_generated_repo_hardening(produced, stage)

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
    base = layout.root / "pr" / "catalog" / service
    base.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sre-kb-pr-") as tmp:
        stage = Path(tmp)
        _stage_pr_tree(stage, layout, proj, service, docs, report)
        merge_tree(stage / "tree", base)

    tree = layout.root / "pr"
    # Fail closed before publish: generated output containing a real secret must be surfaced for
    # human review, not silently scrubbed into an apparently clean tree.
    from sre_kb.security import enforce_secret_gate

    enforce_secret_gate(tree, allow=allow_secrets)
    if dry_run:
        return tree, f"dry-run: staged PR tree at {tree} (would target {sre_repo})"
    ref = get_forge(forge, allowed_repos=allowed_repos).open_pr(
        tree, sre_repo=sre_repo, branch=branch, title=f"SRE KB: {service}", body=_review_md(docs, report)
    )
    return tree, ref
