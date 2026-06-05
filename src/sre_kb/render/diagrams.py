"""Mermaid diagrams from Flow artifacts (a projection of facts we already extracted)."""

from __future__ import annotations

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
    out = ["sequenceDiagram", "  actor Client", f"  participant SVC as {service}"]
    out.append(f"  Client->>SVC: {trigger.get('method', '')} {trigger.get('path', '')}".rstrip())
    for step in spec.get("steps", []):
        peer = _PARTICIPANT.get(step.get("kind", ""), "Dependency")
        out.append(f"  SVC->>{peer}: {step.get('name', 'step')}")
        notes = []
        for fm in step.get("failureModes", []):
            tag = f"{fm.get('mode')}→{fm.get('surfacedAs', '?')}"
            if fm.get("dataLossRisk"):
                tag += " (DATA LOSS)"
            notes.append(tag)
        if notes:
            out.append(f"  note over SVC,{peer}: {'; '.join(notes)}")
    return "\n".join(out)
