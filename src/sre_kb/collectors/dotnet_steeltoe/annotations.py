"""C# collector (AST-backed): [ApiController] endpoints, Confluent.Kafka producers +
swallowed failures, HttpClient egress, EF Core DbContext. Per-class scoping and real
try/catch nodes come from the tree-sitter model; emits the same facts as the Java collector."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import fqn, swallow_level

_HTTP = {"[HttpGet]": "GET", "[HttpPost]": "POST", "[HttpPut]": "PUT", "[HttpDelete]": "DELETE", "[HttpPatch]": "PATCH"}


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.cs"):
        rel = ctx.rel(path)
        module = ctx.module(rel, "csharp")
        ns = module.namespace
        for t in module.types:
            tfqn = fqn(ns, t.name)

            if "[ApiController]" in t.annotations:
                base = t.annotations.get("[Route]", {}).get("", "")
                if base and not base.startswith("/"):
                    base = "/" + base
                for m in t.methods:
                    verb = next((v for a, v in _HTTP.items() if a in m.annotations), None)
                    if not verb:
                        continue
                    route = next((m.annotations[a].get("", "") for a in _HTTP if a in m.annotations), "")
                    path_ = f"{base.rstrip('/')}/{route.lstrip('/')}" if route else base
                    handler = fqn(ns, t.name, m.name)
                    facts.append(Fact(
                        "rest.endpoint",
                        {"method": verb, "path": path_ or "/", "handler": handler},
                        ctx.evidence(rel, m.start, m.name_line, "dotnet_steeltoe.annotations"),
                        Symbol(handler, "method"),
                    ))

            if t.kind == "class" and any("DbContext" in s for s in t.supertypes):
                facts.append(Fact(
                    "db.repository", {"name": t.name},
                    ctx.evidence(rel, t.start, t.start, "dotnet_steeltoe.annotations"),
                    Symbol(fqn(ns, t.name), "class"),
                ))

            for m in t.methods:
                for c in m.calls:
                    rtype = t.fields.get(c.receiver, "")
                    if c.method == "ProduceAsync" and c.str_args:
                        channel = c.str_args[0]
                        facts.append(Fact(
                            "message.egress",
                            {"channel": channel, "client": c.receiver, "broker": "kafka", "class": tfqn},
                            ctx.evidence(rel, c.line, c.line, "dotnet_steeltoe.annotations"),
                            Symbol(tfqn, "class"),
                        ))
                        if c.swallow:
                            sw = c.swallow
                            facts.append(Fact(
                                "swallowed.failure",
                                {"channel": channel, "level": swallow_level(sw.log_method),
                                 "message": sw.message, "class": tfqn},
                                ctx.evidence(rel, sw.start, sw.end, "dotnet_steeltoe.annotations"),
                                Symbol(tfqn, "class"),
                            ))
                    if "HttpClient" in rtype or "httpclient" in c.receiver.lower():
                        if c.method.endswith("Async"):
                            facts.append(Fact(
                                "http.egress", {"class": tfqn},
                                ctx.evidence(rel, c.line, c.line, "dotnet_steeltoe.annotations"),
                                Symbol(tfqn, "class"),
                            ))
    return facts
