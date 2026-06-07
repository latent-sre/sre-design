"""Assemble the per-service PR tree (Backstage-style) under <run>/pr/ and, unless
--dry-run, hand it to a Forge. A REVIEW.md surfaces everything not auto-verified."""

from __future__ import annotations

import shutil
from pathlib import Path

from sre_kb.publish.forge import get_forge
from sre_kb.render.project import load_kb, render_projections, service_name
from sre_kb.workspace import RunLayout


def _review_md(docs: list[dict], report: dict | None) -> str:
    by_status = (report or {}).get("by_status", {})
    lines = ["# SRE KB — review summary", "", f"- artifacts: {len(docs)}"]
    lines += [f"- {k}: {by_status[k]}" for k in sorted(by_status)]
    lines += ["", "## Needs review / not auto-verified", ""]
    any_nr = False
    for r in (report or {}).get("records", []):
        if r.get("status") != "verified":
            any_nr = True
            reasons = [k for k in ("structural", "provenance", "crossref") if r.get(k)]
            extra = f" ({', '.join(reasons)})" if reasons else ""
            lines.append(f"- [ ] {r['artifact']} → {r['status']}{extra}")
    if not any_nr:
        lines.append("- (all verified)")
    return "\n".join(lines) + "\n"


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
) -> tuple[Path, str]:
    docs = docs if docs is not None else load_kb(layout.root)
    proj = layout.root / "projections"
    if not proj.exists():
        render_projections(layout, docs)

    service = service_name(docs)
    base = layout.root / "pr" / "catalog" / service
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    shutil.copytree(layout.kb, base / "kb", dirs_exist_ok=True)
    shutil.copytree(proj / ".github", base / ".github", dirs_exist_ok=True)
    shutil.copytree(proj / "runbooks", base / "runbooks", dirs_exist_ok=True)
    if (proj / "diagrams").exists():
        shutil.copytree(proj / "diagrams", base / "diagrams", dirs_exist_ok=True)
    shutil.copy2(proj / "catalog-info.yaml", base / "catalog-info.yaml")
    (base / "REVIEW.md").write_text(_review_md(docs, report), encoding="utf-8")

    from sre_kb.reporting import collect_findings, render_md

    (base / "FINDINGS.md").write_text(
        render_md(service, layout.run_id, collect_findings(docs), docs), encoding="utf-8"
    )

    tree = layout.root / "pr"
    # Publish-time secret-scan gate (defense-in-depth) — hard-fails even on --dry-run.
    from sre_kb.security import enforce_secret_gate

    enforce_secret_gate(tree, allow=allow_secrets)
    if dry_run:
        return tree, f"dry-run: staged PR tree at {tree} (would target {sre_repo})"
    from sre_kb.publish.policy import enforce_repo_allowlist

    enforce_repo_allowlist(sre_repo)  # fail-closed: only push to an allowlisted repo
    ref = get_forge(forge).open_pr(
        tree, sre_repo=sre_repo, branch=branch, title=f"SRE KB: {service}", body=_review_md(docs, report)
    )
    return tree, ref
