"""Flow deriver (AST-backed): one request flow per endpoint.

Parses the handler's source with tree-sitter and walks the *actual* method invocations in
the handler body, resolving each call's receiver to its field type. That lets us correlate
a call to the right fact precisely — `eventPublisher.publish(...)` maps to the
OrderEventPublisher egress even when several publishers exist — instead of guessing from a
`.publish(` substring. Works for Java (.java) and C# (.cs). Multiple endpoints => multiple
flows; sinks carry stable node names so BlastRadius can aggregate impact.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, FactSet, Symbol
from sre_kb.util import member_of, slug

SAVE_METHODS = {"save", "saveAll", "Save", "SaveAsync"}
_PUBLISH = {"publish", "Publish", "PublishAsync", "ProduceAsync", "send", "Send", "SendAsync"}


def _language_of(rel: str) -> str:
    return "csharp" if rel.endswith(".cs") else "java"


def _short(symbol: str) -> str:
    return symbol.split("#")[0].split(".")[-1] if symbol else ""


def _match_cb(cbs, method: str, rtype: str | None):
    candidates = [cb for cb in cbs if cb.attrs.get("target") == method]
    for cb in candidates:  # prefer an exact receiver field-type match
        cls = _short(cb.attrs.get("targetSymbol") or "")
        if rtype and cls and rtype == cls:
            return cb
    # Unresolved receiver (or no field-type match): attribute to the sole candidate only; never
    # guess the first among several breakers that share a method name (mirrors _match_repo/_match_pub).
    return candidates[0] if len(candidates) == 1 else None


def _match_repo(repos, rtype: str | None):
    for r in repos:
        if rtype == r.attrs.get("name"):
            return r
    # Unresolved receiver: attribute to the sole repo when there's exactly one; never guess
    # the first among several (that fabricated an ungrounded db-write sink).
    return repos[0] if (repos and rtype is None and len(repos) == 1) else None


def _match_pub(pubs, rtype: str | None):
    for p in pubs:
        if rtype and _short(p.attrs.get("class") or "") == rtype:
            return p
    # Fall back to the sole publisher only; an unresolved receiver must not be blamed on the
    # first of several publishers.
    return pubs[0] if (pubs and len(pubs) == 1) else None


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
        module = ctx.module(rel, _language_of(rel))
        handler = ep.attrs.get("handler", "")
        tdecl = next((t for t in module.types if t.name == _short(handler)), None)
        mdecl = next((m for m in tdecl.methods if m.name == handler.split("#")[-1]), None) if tdecl else None
        if not mdecl:
            continue
        fields = tdecl.fields

        raw: list[dict] = []
        for call in mdecl.calls:
            rtype = fields.get(call.receiver)
            cb = _match_cb(cbs, call.method, rtype)
            if cb:
                target = cb.attrs.get("target", "reserve")
                raw.append({
                    "line": call.line, "name": f"call-{slug(target)}", "kind": "http-egress",
                    "failureModes": [{"mode": "timeout", "surfacedAs": "http-503"},
                                     {"mode": "circuit-open", "surfacedAs": "http-503"}],
                    "refs": [{"kind": "ResiliencyPattern", "name": slug(cb.attrs.get("name", "cb")),
                              "relation": "depends-on"}],
                    "sink": {"type": "http", "target": cb.attrs["name"]},
                })
                continue
            if call.method in SAVE_METHODS:
                repo = _match_repo(repos, rtype)
                if repo:
                    # A save inside a logged-and-swallowed catch is silent write loss — the same
                    # data-loss signal the publish branch carries, on the db sink.
                    if call.swallow:
                        fmodes = [{"mode": "db-unavailable", "surfacedAs": "logged-and-swallowed",
                                   "dataLossRisk": True}]
                        refs = [{"kind": "Alert", "name": f"{slug(repo.attrs['name'])}-write-failures",
                                 "relation": "alerts-on"}]
                    else:
                        fmodes = [{"mode": "db-unavailable", "surfacedAs": "http-500"}]
                        refs = []
                    raw.append({
                        "line": call.line, "name": "persist", "kind": "db-write",
                        "failureModes": fmodes,
                        "refs": refs, "sink": {"type": "db", "target": slug(repo.attrs["name"])},
                    })
                    continue
            if call.method in _PUBLISH:
                pub = _match_pub(pubs, rtype)
                if pub:
                    channel = pub.attrs.get("channel", "event")
                    if channel in swallowed:
                        fmodes = [{"mode": "broker-unavailable", "surfacedAs": "logged-and-swallowed",
                                   "dataLossRisk": True}]
                        refs = [{"kind": "Alert", "name": f"{slug(channel)}-publish-failures",
                                 "relation": "alerts-on"}]
                    else:
                        fmodes = [{"mode": "broker-unavailable", "surfacedAs": "propagated"}]
                        refs = []
                    raw.append({
                        "line": call.line, "name": f"publish-{slug(channel)}", "kind": "message-egress",
                        "failureModes": fmodes, "refs": refs, "sink": {"type": "kafka", "target": channel},
                    })
                    continue

        raw.sort(key=lambda s: s["line"])
        if not raw:
            continue
        steps = [
            {"id": f"s{i}", "name": s["name"], "kind": s["kind"],
             "failureModes": s["failureModes"], "refs": s["refs"], "line": s["line"]}
            for i, s in enumerate(raw, 1)
        ]
        flow_name = slug(member_of(handler or "flow"))
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
                        "entrypoint": handler,
                    },
                    "steps": steps,
                    "sinks": [s["sink"] for s in raw],
                },
                ep.evidence,
                Symbol(handler or flow_name, "method"),
            )
        )
    return flows
