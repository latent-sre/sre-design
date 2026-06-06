"""Flow deriver: one request flow per endpoint, scoped to that handler's method body.

For each REST endpoint, brace-scan its handler method body and locate calls to known
sinks (circuit-breaker target, repository save, publisher); order steps by source line.
Each step carries its own call-site line for provenance, and a stable sink node name so
BlastRadius can aggregate impact across flows. Multiple endpoints => multiple flows.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, FactSet, Symbol
from sre_kb.util import member_of, slug

_SAVE_CALLS = [".save(", ".Save(", ".SaveChanges"]
_PUBLISH_CALLS = [".publish(", ".Publish(", ".PublishAsync(", ".ProduceAsync("]


def _method_span(lines: list[str], decl0: int) -> tuple[int, int]:
    """0-based [start, end] span of the method body whose declaration is near line decl0."""
    i = decl0
    while i < len(lines) and "{" not in lines[i] and i - decl0 <= 3:
        i += 1
    if i >= len(lines) or "{" not in lines[i]:
        return decl0, min(decl0 + 40, len(lines) - 1)
    depth = 0
    for j in range(i, len(lines)):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0:
            return decl0, j
    return decl0, len(lines) - 1


def _match_pub(pubs: list, body: str):
    """Pick the publisher fact for this body — by channel slug if it appears, else the first."""
    if len(pubs) <= 1:
        return pubs[0] if pubs else None
    low = body.lower()
    for p in pubs:
        head = slug(str(p.attrs.get("channel", ""))).split("-")[0]
        if head and head in low:
            return p
    return pubs[0]


def collect(ctx: ScanContext, fs: FactSet) -> list[Fact]:
    endpoints = fs.of("rest.endpoint")
    if not endpoints:
        return []
    cbs = fs.of("resiliency.circuitbreaker")
    repos = fs.of("db.repository")
    pubs = fs.of("message.egress")
    swallowed = {s.attrs.get("channel"): s for s in fs.of("swallowed.failure")}

    flows: list[Fact] = []
    for ep in endpoints:
        rel = ep.evidence.path
        lines = ctx.read_lines(rel)
        decl0 = max(0, (ep.evidence.lines.end or 1) - 1)
        lo, hi = _method_span(lines, decl0)
        body = "".join(lines[lo : hi + 1])

        def find_call(calls: list[str], _lo=lo, _hi=hi, _lines=lines) -> int | None:
            for n in range(_lo, _hi + 1):
                if any(c in _lines[n] for c in calls):
                    return n + 1
            return None

        raw: list[dict] = []
        for cb in cbs:
            target = cb.attrs.get("target", "reserve")
            ln = find_call([f".{target}("])
            if ln:
                raw.append({
                    "line": ln, "name": f"call-{slug(target)}", "kind": "http-egress",
                    "failureModes": [{"mode": "timeout", "surfacedAs": "http-503"},
                                     {"mode": "circuit-open", "surfacedAs": "http-503"}],
                    "refs": [{"kind": "ResiliencyPattern", "name": slug(cb.attrs.get("name", "cb")),
                              "relation": "depends-on"}],
                    "sink": {"type": "http", "target": cb.attrs["name"]},
                })
        if repos:
            ln = find_call(_SAVE_CALLS)
            if ln:
                raw.append({
                    "line": ln, "name": "persist", "kind": "db-write",
                    "failureModes": [{"mode": "db-unavailable", "surfacedAs": "http-500"}],
                    "refs": [], "sink": {"type": "db", "target": slug(repos[0].attrs["name"])},
                })
        pub = _match_pub(pubs, body)
        if pub:
            ln = find_call(_PUBLISH_CALLS)
            if ln:
                channel = pub.attrs.get("channel", "event")
                if channel in swallowed:
                    fmodes = [{"mode": "broker-unavailable", "surfacedAs": "logged-and-swallowed", "dataLossRisk": True}]
                    refs = [{"kind": "Alert", "name": f"{slug(channel)}-publish-failures", "relation": "alerts-on"}]
                else:
                    fmodes = [{"mode": "broker-unavailable", "surfacedAs": "propagated"}]
                    refs = []
                raw.append({
                    "line": ln, "name": f"publish-{slug(channel)}", "kind": "message-egress",
                    "failureModes": fmodes, "refs": refs, "sink": {"type": "kafka", "target": channel},
                })

        raw.sort(key=lambda s: s["line"])
        if not raw:
            continue  # no recognized sink in this handler's body -> not a derivable flow
        steps = [
            {"id": f"s{i}", "name": s["name"], "kind": s["kind"],
             "failureModes": s["failureModes"], "refs": s["refs"], "line": s["line"]}
            for i, s in enumerate(raw, 1)
        ]
        flow_name = slug(member_of(ep.attrs.get("handler", "flow")))
        flows.append(
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
                    "sinks": [s["sink"] for s in raw],
                },
                ep.evidence,
                Symbol(ep.attrs.get("handler", flow_name), "method"),
            )
        )
    return flows
