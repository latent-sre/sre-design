"""Assemble per-service projections (Copilot instructions, runbooks, diagrams, catalog)
into <run>/projections/ from the validated KB."""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.render.catalog import catalog_info
from sre_kb.render.copilot import copilot_instructions, runbook_markdown
from sre_kb.render.diagrams import mermaid_sequence
from sre_kb.workspace import RunLayout


def load_kb(run_root: Path) -> list[dict]:
    docs: list[dict] = []
    for p in sorted((run_root / "kb").rglob("*.yaml")):
        docs.append(yaml.safe_load(p.read_text(encoding="utf-8")))
    return docs


def service_name(docs: list[dict]) -> str:
    for d in docs:
        svc = (d.get("metadata") or {}).get("service")
        if svc:
            return svc
    return "service"


def render_projections(layout: RunLayout, docs: list[dict] | None = None) -> Path:
    docs = docs if docs is not None else load_kb(layout.root)
    proj = layout.root / "projections"
    (proj / ".github").mkdir(parents=True, exist_ok=True)
    (proj / "runbooks").mkdir(parents=True, exist_ok=True)
    (proj / "diagrams").mkdir(parents=True, exist_ok=True)

    service = service_name(docs)
    flows = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Flow"}

    (proj / ".github" / "copilot-instructions.md").write_text(
        copilot_instructions(service, docs), encoding="utf-8"
    )
    (proj / "catalog-info.yaml").write_text(
        yaml.safe_dump(catalog_info(service, docs), sort_keys=False), encoding="utf-8"
    )
    for name, flow in flows.items():
        (proj / "diagrams" / f"{name}.mmd").write_text(mermaid_sequence(flow), encoding="utf-8")
    for d in docs:
        if d["kind"] == "Runbook":
            related = flows.get(d["spec"].get("relatedFlow"))
            (proj / "runbooks" / f"{d['metadata']['name']}.md").write_text(
                runbook_markdown(d, related), encoding="utf-8"
            )
    return proj
