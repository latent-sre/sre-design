"""Mermaid diagrams from Flow + Topology artifacts (projections of facts we extracted)."""

from __future__ import annotations

import re


# Untrusted strings (service/path from annotations, resource names from manifests) flow into
# Mermaid labels/messages. Strip the metacharacters that could break out of a label or inject
# diagram syntax, mirroring the sanitization applied to node ids — render-integrity, not RCE.
def _mm(text: object) -> str:
    s = re.sub(r"\s+", " ", str(text))
    return re.sub(r'[;:|<>"#%(){}\[\]`\\]', "", s).strip()


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
    "external": '{{"{}"}}',
}


def mermaid_topology(topology: dict) -> str:
    spec = topology.get("spec", {})

    def nid(name: str) -> str:
        return "n_" + re.sub(r"[^A-Za-z0-9]", "_", name)

    out = ["graph LR"]
    for node in spec.get("nodes", []):
        label = _SHAPE.get(node.get("type", "service"), '["{}"]').format(_mm(node["name"]))
        out.append(f"  {nid(node['name'])}{label}")
    for e in spec.get("edges", []):
        rel = _mm(e.get("relation", ""))
        out.append(f"  {nid(e['from'])} -->|{rel}| {nid(e['to'])}")
    return "\n".join(out)
