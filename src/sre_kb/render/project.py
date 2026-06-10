"""Assemble per-service projections (Copilot instructions, runbooks, diagrams, catalog)
into <run>/projections/ from the validated KB."""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.render.catalog import catalog_info
from sre_kb.render.copilot import copilot_instructions, runbook_markdown
from sre_kb.render.diagrams import (
    TOPOLOGY_LEGEND,
    architecture_caption,
    diagram_markdown,
    known_http_clients,
    mermaid_architecture,
    mermaid_sequence,
    mermaid_topology,
    topology_overlays,
)
from sre_kb.registry import renderer_for
from sre_kb.workspace import RunLayout


def load_kb(run_root: Path) -> list[dict]:
    """Load the run's validated KB tree, canonicalizing schema-evolution aliases on the way
    in (§1.6): a doc written against a renamed field's old name reads identically to a new
    one everywhere downstream — renderers, findings, narrations — not just in validation."""
    from sre_kb.validation.structural import canonicalize_doc

    docs: list[dict] = []
    for p in sorted((run_root / "kb").rglob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        canonical, _ = canonicalize_doc(doc) if isinstance(doc, dict) else (doc, [])
        docs.append(canonical)
    return docs


def service_name(docs: list[dict]) -> str:
    for d in docs:
        svc = (d.get("metadata") or {}).get("service")
        if svc:
            return svc
    return "service"


def _render_diagram(doc: dict, proj: Path, flows: dict[str, dict], docs: list[dict]) -> None:
    name = doc["metadata"]["name"]
    src = mermaid_sequence(doc, known_targets=known_http_clients(docs))
    (proj / "diagrams" / f"{name}.mmd").write_text(src, encoding="utf-8")
    (proj / "diagrams" / f"{name}.md").write_text(
        diagram_markdown(f"{name} — flow", src), encoding="utf-8"
    )


def _render_runbook(doc: dict, proj: Path, flows: dict[str, dict], docs: list[dict]) -> None:
    related = flows.get(doc["spec"].get("relatedFlow"))
    (proj / "runbooks" / f"{doc['metadata']['name']}.md").write_text(
        runbook_markdown(doc, related, known_targets=known_http_clients(docs)), encoding="utf-8"
    )


def _render_topology(doc: dict, proj: Path, flows: dict[str, dict], docs: list[dict]) -> None:
    name = doc["metadata"]["name"]
    tiers, lossy = topology_overlays(doc, docs)
    src = mermaid_topology(doc, tiers=tiers, lossy=lossy)
    (proj / "diagrams" / f"{name}-topology.mmd").write_text(src, encoding="utf-8")
    (proj / "diagrams" / f"{name}-topology.md").write_text(
        diagram_markdown(f"{name} — topology", src, TOPOLOGY_LEGEND), encoding="utf-8"
    )


def _render_architecture(doc: dict, proj: Path, flows: dict[str, dict], docs: list[dict]) -> None:
    name = doc["metadata"]["name"]
    src = mermaid_architecture(doc)
    (proj / "diagrams" / f"{name}-architecture.mmd").write_text(src, encoding="utf-8")
    (proj / "diagrams" / f"{name}-architecture.md").write_text(
        diagram_markdown(f"{name} — architecture", src, architecture_caption(doc)),
        encoding="utf-8")


# Per-kind projection renderers, keyed by the registry's `renderer` field. Adding a projecting kind =
# declare `renderer: <name>` in the registry + add a handler here; test_registry_governance keeps the
# two in lock-step. Whole-KB projections (copilot-instructions, catalog-info) are not per-kind.
_PROJECTION_RENDERERS = {"diagram": _render_diagram, "runbook": _render_runbook,
                         "topology": _render_topology, "architecture": _render_architecture}


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
