"""Flow deriver: stitch a request flow from an endpoint to its sinks.

Bounded approximation: from the controller handler, locate calls to known sinks
(circuit-breaker target, repository save, publisher) and order them by source line.
Each step carries its own call-site line for provenance.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, FactSet, Symbol
from sre_kb.util import find_line, member_of, slug


def collect(ctx: ScanContext, fs: FactSet) -> list[Fact]:
    endpoints = fs.of("rest.endpoint")
    if not endpoints:
        return []
    ep = endpoints[0]
    rel = ep.evidence.path
    lines = ctx.read_lines(rel)

    cb = fs.first("resiliency.circuitbreaker")
    repo = fs.first("db.repository")
    pub = fs.first("message.egress")
    swallowed = fs.first("swallowed.failure")

    raw: list[dict] = []

    def add(calls: list[str], name: str, kind: str, failure_modes: list[dict], refs: list[dict]) -> None:
        ln = next((find_line(lines, c) for c in calls if find_line(lines, c)), None)
        if ln:
            raw.append({"line": ln, "name": name, "kind": kind, "failureModes": failure_modes, "refs": refs})

    if cb:
        target = cb.attrs.get("target", "reserve")
        add(
            [f".{target}("],
            f"call-{slug(target)}",
            "http-egress",
            [{"mode": "timeout", "surfacedAs": "http-503"}, {"mode": "circuit-open", "surfacedAs": "http-503"}],
            [{"kind": "ResiliencyPattern", "name": slug(cb.attrs.get("name", "cb")), "relation": "depends-on"}],
        )
    if repo:
        add(
            [".save(", ".Save(", ".SaveChanges"],
            "persist",
            "db-write",
            [{"mode": "db-unavailable", "surfacedAs": "http-500"}],
            [],
        )
    if pub:
        channel = pub.attrs.get("channel", "event")
        if swallowed:
            fmodes = [{"mode": "broker-unavailable", "surfacedAs": "logged-and-swallowed", "dataLossRisk": True}]
            refs = [{"kind": "Alert", "name": f"{slug(channel)}-publish-failures", "relation": "alerts-on"}]
        else:
            fmodes = [{"mode": "broker-unavailable", "surfacedAs": "propagated"}]
            refs = []
        add(
            [".publish(", ".Publish(", ".PublishAsync(", ".ProduceAsync("],
            f"publish-{slug(channel)}",
            "message-egress",
            fmodes,
            refs,
        )

    raw.sort(key=lambda s: s["line"])
    steps = []
    for idx, s in enumerate(raw, 1):
        steps.append(
            {
                "id": f"s{idx}",
                "name": s["name"],
                "kind": s["kind"],
                "failureModes": s["failureModes"],
                "refs": s["refs"],
                "line": s["line"],
            }
        )

    sinks = []
    if cb:
        sinks.append({"type": "http", "target": cb.attrs.get("name", "downstream")})
    if repo:
        sinks.append({"type": "db", "target": slug(repo.attrs.get("name", "store"))})
    if pub:
        sinks.append({"type": "kafka", "target": pub.attrs.get("channel", "event")})

    flow_name = slug(member_of(ep.attrs.get("handler", "flow")))
    return [
        Fact(
            "flow.flow",
            {
                "name": flow_name,
                "path": rel,
                "trigger": {
                    "type": "http",
                    "method": ep.attrs.get("method"),
                    "path": ep.attrs.get("path"),
                    "entrypoint": ep.attrs.get("handler"),
                },
                "steps": steps,
                "sinks": sinks,
            },
            ep.evidence,
            Symbol(ep.attrs.get("handler", flow_name), "method"),
        )
    ]
