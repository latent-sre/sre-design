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

TOPOLOGY_LEGEND = ("Legend: rectangle = service · rounded = datastore · trapezoid = broker · "
                   "stadium (dashed) = topic · double rectangle = other bound resource · "
                   "round-edged rectangle = internal library · hexagon = external.")


def mermaid_topology(topology: dict) -> str:
    spec = topology.get("spec", {})

    def nid(name: str) -> str:
        return "n_" + re.sub(r"[^A-Za-z0-9]", "_", name)

    out = ["graph LR"]
    used_types: set[str] = set()
    for node in spec.get("nodes", []):
        name = node.get("name")
        if not name:
            continue  # a node with no name can't be rendered; skip rather than KeyError
        ntype = node.get("type", "service")
        label = _SHAPE.get(ntype, '["{}"]').format(_mm(name))
        out.append(f"  {nid(name)}{label}")
        if ntype in _CLASS_STYLE:
            out.append(f"  class {nid(name)} {ntype}")
            used_types.add(ntype)
    for e in spec.get("edges", []):
        src, dst = e.get("from"), e.get("to")
        if not src or not dst:
            continue  # an edge missing an endpoint can't be drawn
        rel = _mm(e.get("relation", ""))
        out.append(f"  {nid(src)} -->|{rel}| {nid(dst)}")
    for ntype in sorted(used_types):
        out.append(f"  classDef {ntype} {_CLASS_STYLE[ntype]}")
    return "\n".join(out)


def diagram_markdown(title: str, mermaid_src: str, legend: str | None = None) -> str:
    """A GitHub-renderable wrapper: the same Mermaid source in a fenced block, so the diagram
    draws inline in PRs and the published KB without tooling. The title is sanitized like any
    other untrusted label."""
    parts = [f"# {_mm(title)}", "", "```mermaid", mermaid_src, "```"]
    if legend:
        parts += ["", legend]
    return "\n".join(parts) + "\n"
