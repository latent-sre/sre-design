"""Mermaid diagrams from Flow + Topology artifacts (projections of facts we extracted)."""

from __future__ import annotations

import re

# Untrusted strings (service/path from annotations, resource names from manifests) flow into Mermaid
# labels/messages. `_mm` strips the metacharacters that could break out of a label or inject diagram
# syntax — render-integrity, not RCE. It lives in `render.templating` (registered there as the
# `mermaid` Jinja filter too) so the sanitizer has exactly one definition across templates and Python.
from sre_kb.render.templating import mermaid as _mm

_PARTICIPANT = {
    "http-egress": "Downstream",
    "db-write": "Datastore",
    "db-read": "Datastore",
    "message-egress": "Broker",
}


def mermaid_sequence(flow: dict) -> str:
    spec = flow.get("spec", {})
    trigger = spec.get("trigger", {})
    service = (flow.get("metadata") or {}).get("service", "service")
    out = ["sequenceDiagram", "  actor Client", f"  participant SVC as {_mm(service)}"]
    out.append(f"  Client->>SVC: {_mm(trigger.get('method', ''))} {_mm(trigger.get('path', ''))}".rstrip())
    for step in spec.get("steps", []):
        peer = _PARTICIPANT.get(step.get("kind", ""), "Dependency")
        out.append(f"  SVC->>{peer}: {_mm(step.get('name', 'step'))}")
        notes = []
        for fm in step.get("failureModes", []):
            tag = f"{_mm(fm.get('mode'))}→{_mm(fm.get('surfacedAs', '?'))}"
            if fm.get("dataLossRisk"):
                tag += " (DATA LOSS)"
            notes.append(tag)
        if notes:
            out.append(f"  note over SVC,{peer}: {'; '.join(notes)}")
    return "\n".join(out)


_SHAPE = {
    "service": '["{}"]',
    "datastore": '[("{}")]',
    "broker": '[/"{}"/]',
    "topic": '(["{}"])',
    "resource": '[["{}"]]',
    "library": '("{}")',
    "external": '{{"{}"}}',
}


# Node styling by type. Class names and styles come ONLY from this fixed engine vocabulary —
# an unknown (possibly hand-authored) node type renders unstyled rather than letting scanned
# strings reach a Mermaid class/style line.
_CLASS_STYLE = {
    "service": "fill:#e8f0fe,stroke:#1a73e8",
    "datastore": "fill:#e6f4ea,stroke:#188038",
    "broker": "fill:#fef7e0,stroke:#f9ab00",
    "topic": "fill:#fef7e0,stroke:#f9ab00,stroke-dasharray: 3 3",
    "resource": "fill:#f3e8fd,stroke:#9334e6",
    "library": "fill:#e0f7fa,stroke:#00838f",
    "external": "fill:#f1f3f4,stroke:#5f6368",
}

# Criticality-tier styling for service nodes (NEXT-INCREMENTS §2.1). Same rule as
# _CLASS_STYLE: only a tier value present in THIS fixed vocabulary ever reaches a class
# line — an artifact carrying anything else renders with the plain service style.
_TIER_STYLE = {
    "tier0": "fill:#e8f0fe,stroke:#d93025,stroke-width:3px",
    "tier1": "fill:#e8f0fe,stroke:#f9ab00,stroke-width:2.5px",
    "tier2": "fill:#e8f0fe,stroke:#1a73e8,stroke-width:1.5px",
    "tier3": "fill:#e8f0fe,stroke:#5f6368",
}

_LOSSY_EDGE_STYLE = "stroke:#d93025,stroke-width:2px,stroke-dasharray:4 2"

TOPOLOGY_LEGEND = ("Legend: rectangle = service · rounded = datastore · trapezoid = broker · "
                   "stadium (dashed) = topic · double rectangle = other bound resource · "
                   "round-edged rectangle = internal library · hexagon = external. "
                   "A red/amber service border marks criticality tier0/tier1; a red dashed "
                   "edge feeds a node where failure loses data.")


def topology_overlays(topology: dict, docs: list[dict]) -> tuple[dict[str, str], set[str]]:
    """The (tiers, lossy) styling joins for a Topology, from sibling artifacts: Criticality
    gives each service node its tier; BlastRadius.stateful.dataLossRisk marks the nodes whose
    incoming writes can be lost. A BlastRadius node names the code-side target (repository
    slug, channel) while topology nodes carry the platform binding name, so attribution is a
    direct (slug) match or — when exactly one topology node has the matching type — the sole
    node the write can be going to (the same rule the estate co-tenancy join uses)."""
    from sre_kb.util import slug

    nodes = {n.get("name"): n.get("type", "service")
             for n in (topology.get("spec") or {}).get("nodes", []) if n.get("name")}
    tiers: dict[str, str] = {}
    lossy: set[str] = set()
    for d in docs:
        spec = d.get("spec") or {}
        if d.get("kind") == "Criticality" and spec.get("tier") in _TIER_STYLE:
            svc = (d.get("metadata") or {}).get("service")
            if nodes.get(svc) == "service":
                tiers[svc] = spec["tier"]
        elif d.get("kind") == "BlastRadius" and (spec.get("stateful") or {}).get("dataLossRisk"):
            node = spec.get("node") or {}
            target = slug(str(node.get("name")))
            direct = next((n for n in nodes if slug(n) == target), None)
            of_type = [n for n, t in nodes.items() if t == node.get("type")]
            if direct:
                lossy.add(direct)
            elif len(of_type) == 1:
                lossy.add(of_type[0])
    return tiers, lossy


def mermaid_topology(topology: dict, tiers: dict[str, str] | None = None,
                     lossy: set[str] | None = None) -> str:
    spec = topology.get("spec", {})
    tiers = tiers or {}
    lossy = lossy or set()

    def nid(name: str) -> str:
        return "n_" + re.sub(r"[^A-Za-z0-9]", "_", name)

    out = ["graph LR"]
    used_types: set[str] = set()
    used_tiers: set[str] = set()
    for node in spec.get("nodes", []):
        name = node.get("name")
        if not name:
            continue  # a node with no name can't be rendered; skip rather than KeyError
        ntype = node.get("type", "service")
        label = _SHAPE.get(ntype, '["{}"]').format(_mm(name))
        out.append(f"  {nid(name)}{label}")
        tier = tiers.get(name)
        if ntype == "service" and tier in _TIER_STYLE:
            out.append(f"  class {nid(name)} {tier}")
            used_tiers.add(tier)
        elif ntype in _CLASS_STYLE:
            out.append(f"  class {nid(name)} {ntype}")
            used_types.add(ntype)
    lossy_edges: list[int] = []
    n_edges = 0
    for e in spec.get("edges", []):
        src, dst = e.get("from"), e.get("to")
        if not src or not dst:
            continue  # an edge missing an endpoint can't be drawn
        rel = _mm(e.get("relation", ""))
        out.append(f"  {nid(src)} -->|{rel}| {nid(dst)}")
        if dst in lossy:
            lossy_edges.append(n_edges)
        n_edges += 1
    for ntype in sorted(used_types):
        out.append(f"  classDef {ntype} {_CLASS_STYLE[ntype]}")
    for tier in sorted(used_tiers):
        out.append(f"  classDef {tier} {_TIER_STYLE[tier]}")
    if lossy_edges:
        idx = ",".join(str(i) for i in lossy_edges)
        out.append(f"  linkStyle {idx} {_LOSSY_EDGE_STYLE}")
    return "\n".join(out)


def diagram_markdown(title: str, mermaid_src: str, legend: str | None = None) -> str:
    """A GitHub-renderable wrapper: the same Mermaid source in a fenced block, so the diagram
    draws inline in PRs and the published KB without tooling. The title is sanitized like any
    other untrusted label."""
    parts = [f"# {_mm(title)}", "", "```mermaid", mermaid_src, "```"]
    if legend:
        parts += ["", legend]
    return "\n".join(parts) + "\n"
