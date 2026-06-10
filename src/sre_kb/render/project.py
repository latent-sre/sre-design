"""Assemble per-service projections (Copilot instructions, runbooks, diagrams, catalog)
into <run>/projections/ from the validated KB."""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.render.catalog import catalog_info
from sre_kb.render.copilot import copilot_instructions, runbook_markdown
from sre_kb.render.diagrams import (
    TOPOLOGY_LEGEND,
    diagram_markdown,
    mermaid_sequence,
    mermaid_topology,
    topology_overlays,
)
from sre_kb.registry import renderer_for
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


def _render_diagram(doc: dict, proj: Path, flows: dict[str, dict], docs: list[dict]) -> None:
    from sre_kb.util import slug

    name = doc["metadata"]["name"]
    # Configured HTTP clients are known downstreams: name them in the sequence diagram
    # instead of collapsing every egress into the generic `Downstream` participant.
    known = {slug(d["spec"]["name"]): d["spec"]["name"] for d in docs
             if d.get("kind") == "Dependency" and (d.get("spec") or {}).get("type") == "http"}
    src = mermaid_sequence(doc, known_targets=known)
    (proj / "diagrams" / f"{name}.mmd").write_text(src, encoding="utf-8")
    (proj / "diagrams" / f"{name}.md").write_text(
        diagram_markdown(f"{name} — flow", src), encoding="utf-8"
    )


def _render_runbook(doc: dict, proj: Path, flows: dict[str, dict], docs: list[dict]) -> None:
    related = flows.get(doc["spec"].get("relatedFlow"))
    (proj / "runbooks" / f"{doc['metadata']['name']}.md").write_text(
        runbook_markdown(doc, related), encoding="utf-8"
    )


def _render_topology(doc: dict, proj: Path, flows: dict[str, dict], docs: list[dict]) -> None:
    name = doc["metadata"]["name"]
    tiers, lossy = topology_overlays(doc, docs)
    src = mermaid_topology(doc, tiers=tiers, lossy=lossy)
    (proj / "diagrams" / f"{name}-topology.mmd").write_text(src, encoding="utf-8")
    (proj / "diagrams" / f"{name}-topology.md").write_text(
        diagram_markdown(f"{name} — topology", src, TOPOLOGY_LEGEND), encoding="utf-8"
    )


# Per-kind projection renderers, keyed by the registry's `renderer` field. Adding a projecting kind =
# declare `renderer: <name>` in the registry + add a handler here; test_registry_governance keeps the
# two in lock-step. Whole-KB projections (copilot-instructions, catalog-info) are not per-kind.
_PROJECTION_RENDERERS = {"diagram": _render_diagram, "runbook": _render_runbook,
                         "topology": _render_topology}


def render_projections(layout: RunLayout, docs: list[dict] | None = None) -> Path:
    docs = docs if docs is not None else load_kb(layout.root)
    proj = layout.root / "projections"
    (proj / ".github").mkdir(parents=True, exist_ok=True)
    (proj / "runbooks").mkdir(parents=True, exist_ok=True)
    (proj / "diagrams").mkdir(parents=True, exist_ok=True)

    service = service_name(docs)
    flows = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Flow"}

    # Whole-KB projections (every artifact contributes).
    (proj / ".github" / "copilot-instructions.md").write_text(
        copilot_instructions(service, docs), encoding="utf-8"
    )
    (proj / "catalog-info.yaml").write_text(
        yaml.safe_dump(catalog_info(service, docs), sort_keys=False), encoding="utf-8"
    )

    # Per-kind projections, dispatched by the kind's registry-declared renderer.
    for d in docs:
        handler = _PROJECTION_RENDERERS.get(renderer_for(d.get("kind")))
        if handler:
            handler(d, proj, flows, docs)
    return proj
