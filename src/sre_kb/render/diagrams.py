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


def mermaid_sequence(flow: dict, known_targets: dict[str, str] | None = None) -> str:
    """`known_targets` (slug -> display name) promotes an http-egress step whose sink target is
    a configured client to a named participant instead of the `Downstream` catch-all. Targets
    live on the index-parallel `sinks` list, so pairing applies only when the deriver built
    steps and sinks in one ordered walk (the `_lossy_sink` guard); otherwise every step keeps
    its generic participant rather than mispairing."""
    from sre_kb.util import slug

    spec = flow.get("spec", {})
    trigger = spec.get("trigger", {})
    service = (flow.get("metadata") or {}).get("service", "service")
    steps = spec.get("steps", [])
    sinks = spec.get("sinks", [])
    paired = sinks if known_targets and len(sinks) == len(steps) else [None] * len(steps)

    def peer_of(step: dict, sink: dict | None) -> tuple[str, str | None]:
        """(participant id, display name to declare or None for the generic vocabulary)."""
        if step.get("kind") == "http-egress" and isinstance(sink, dict):
            target = slug(str(sink.get("target")))
            if known_targets and target in known_targets:
                return "P_" + re.sub(r"[^A-Za-z0-9]", "_", target), known_targets[target]
        return _PARTICIPANT.get(step.get("kind", ""), "Dependency"), None

    out = ["sequenceDiagram", "  actor Client", f"  participant SVC as {_mm(service)}"]
    declared: set[str] = set()
    for step, sink in zip(steps, paired):
        pid, label = peer_of(step, sink)
        if label is not None and pid not in declared:
            declared.add(pid)
            out.append(f"  participant {pid} as {_mm(label)}")
    out.append(f"  Client->>SVC: {_mm(trigger.get('method', ''))} {_mm(trigger.get('path', ''))}".rstrip())
    for step, sink in zip(steps, paired):
        peer, _ = peer_of(step, sink)
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
    "frontend": '[/"{}"\\]',
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
    "frontend": "fill:#fce8e6,stroke:#c5221f",
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

TOPOLOGY_LEGEND = ("Legend: rectangle = service · slanted rectangle = frontend (SPA) · "
                   "rounded = datastore · trapezoid = broker · "
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


_SHARED_GROUP = "shared (co-tenant)"


def _groups(nodes: dict[str, str], edges: list[dict]) -> dict[str, str] | None:
    """Subgraph assignment for a multi-service topology: a non-service node touched by exactly
    one service joins that service's cluster; one touched by several joins the shared
    (co-tenant) cluster — the grouping that makes blast radius legible. Returns None for a
    single-service topology (flat rendering, as before)."""
    services = [n for n, t in nodes.items() if t in ("service", "frontend")]
    if len(services) < 2:
        return None
    owners: dict[str, set[str]] = {}
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src in services and dst in nodes and dst not in services:
            owners.setdefault(dst, set()).add(src)
        elif dst in services and src in nodes and src not in services:
            owners.setdefault(src, set()).add(dst)
    group: dict[str, str] = {s: s for s in services}
    for n, owning in owners.items():
        group[n] = next(iter(owning)) if len(owning) == 1 else _SHARED_GROUP
    return group


def mermaid_topology(topology: dict, tiers: dict[str, str] | None = None,
                     lossy: set[str] | None = None) -> str:
    spec = topology.get("spec", {})
    tiers = tiers or {}
    lossy = lossy or set()

    def nid(name: str) -> str:
        return "n_" + re.sub(r"[^A-Za-z0-9]", "_", name)

    nodes = {n["name"]: n.get("type", "service")
             for n in spec.get("nodes", [])
             if n.get("name")}  # a node with no name can't be rendered; skip rather than KeyError
    edges = [e for e in spec.get("edges", [])
             if e.get("from") and e.get("to")]  # an edge missing an endpoint can't be drawn

    node_lines: dict[str, str] = {}
    class_lines: list[str] = []
    used_types: set[str] = set()
    used_tiers: set[str] = set()
    for name, ntype in nodes.items():
        node_lines[name] = f"{nid(name)}{_SHAPE.get(ntype, '[\"{}\"]').format(_mm(name))}"
        tier = tiers.get(name)
        if ntype == "service" and tier in _TIER_STYLE:
            class_lines.append(f"  class {nid(name)} {tier}")
            used_tiers.add(tier)
        elif ntype in _CLASS_STYLE:
            class_lines.append(f"  class {nid(name)} {ntype}")
            used_types.add(ntype)

    out = ["graph LR"]
    group = _groups(nodes, edges)
    if group is None:
        out += [f"  {line}" for line in node_lines.values()]
    else:
        clusters: dict[str, list[str]] = {}
        for name in nodes:
            clusters.setdefault(group.get(name, _SHARED_GROUP), []).append(name)
        # Service clusters first (stable name order), the shared cluster last.
        for cluster in sorted(clusters, key=lambda c: (c == _SHARED_GROUP, c)):
            out.append(f'  subgraph sg_{re.sub(r"[^A-Za-z0-9]", "_", cluster)}["{_mm(cluster)}"]')
            out += [f"    {node_lines[name]}" for name in clusters[cluster]]
            out.append("  end")

    lossy_edges: list[int] = []
    for i, e in enumerate(edges):
        rel = _mm(e.get("relation", ""))
        out.append(f"  {nid(e['from'])} -->|{rel}| {nid(e['to'])}")
        if e["to"] in lossy:
            lossy_edges.append(i)
    out += class_lines
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
