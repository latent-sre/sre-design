"""Spring collector (AST-backed): REST endpoints, message publishers, repositories, HTTP
egress, and swallowed-failure detection.

Per-class scoping comes from the AST, so facts are attributed to their actual enclosing
type (the line-regex version used the first class in the file). Receiver/type resolution
and real try/catch nodes replace the substring + brace-counting heuristics.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.parsing import parse
from sre_kb.util import fqn

_MAPPING = {
    "@GetMapping": "GET", "@PostMapping": "POST", "@PutMapping": "PUT",
    "@DeleteMapping": "DELETE", "@PatchMapping": "PATCH",
}


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        module = parse("java", ctx.read_text(rel))
        ns = module.namespace
        for t in module.types:
            tfqn = fqn(ns, t.name)

            if "@RestController" in t.annotations:
                base = t.annotations.get("@RequestMapping", {}).get("", "")
                for m in t.methods:
                    verb = next((v for ann, v in _MAPPING.items() if ann in m.annotations), None)
                    if not verb:
                        continue
                    sub = next((m.annotations[ann].get("", "") for ann in _MAPPING if ann in m.annotations), "")
                    handler = fqn(ns, t.name, m.name)
                    facts.append(Fact(
                        "rest.endpoint",
                        {"method": verb, "path": (base + sub) or "/", "handler": handler},
                        ctx.evidence(rel, m.start, m.name_line, "java_spring.annotations"),
                        Symbol(handler, "method"),
                    ))

            if t.kind == "interface" and any("JpaRepository" in s for s in t.supertypes):
                facts.append(Fact(
                    "db.repository", {"name": t.name},
                    ctx.evidence(rel, t.start, t.start, "java_spring.annotations"),
                    Symbol(fqn(ns, t.name), "interface"),
                ))

            for m in t.methods:
                for c in m.calls:
                    rtype = t.fields.get(c.receiver, "")
                    if c.method == "send" and c.str_args and ("kafka" in c.receiver.lower() or "Kafka" in rtype):
                        channel = c.str_args[0]
                        facts.append(Fact(
                            "message.egress",
                            {"channel": channel, "client": c.receiver, "broker": "kafka", "class": tfqn},
                            ctx.evidence(rel, c.line, c.line, "java_spring.annotations"),
                            Symbol(tfqn, "class"),
                        ))
                        if c.swallow:
                            sw = c.swallow
                            facts.append(Fact(
                                "swallowed.failure",
                                {"channel": channel, "level": sw.log_method, "message": sw.message, "class": tfqn},
                                ctx.evidence(rel, sw.start, sw.end, "java_spring.annotations"),
                                Symbol(tfqn, "class"),
                            ))
                    if c.receiver == "restTemplate" or "RestTemplate" in rtype:
                        facts.append(Fact(
                            "http.egress", {"class": tfqn},
                            ctx.evidence(rel, c.line, c.line, "java_spring.annotations"),
                            Symbol(tfqn, "class"),
                        ))
    return facts
