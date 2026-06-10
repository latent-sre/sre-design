"""Spring collector (AST-backed): REST endpoints, message publishers, repositories, HTTP
egress, and swallowed-failure detection.

Per-class scoping comes from the AST, so facts are attributed to their actual enclosing
type (the line-regex version used the first class in the file). Receiver/type resolution
and real try/catch nodes replace the substring + brace-counting heuristics.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.java_spring.flow_builder import SAVE_METHODS
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import fqn, swallow_level

_MAPPING = {
    "@GetMapping": "GET", "@PostMapping": "POST", "@PutMapping": "PUT",
    "@DeleteMapping": "DELETE", "@PatchMapping": "PATCH",
}
_AUTHZ = ("@PreAuthorize", "@Secured", "@RolesAllowed")


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        module = ctx.module(rel, "java")
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

            for owner, anns, line in [(tfqn, t.annotations, t.start)] + [
                (fqn(ns, t.name, m.name), m.annotations, m.start) for m in t.methods
            ]:
                ann = next((a for a in _AUTHZ if a in anns), None)
                if ann:
                    facts.append(Fact(
                        "security.authz", {"annotation": ann, "target": owner},
                        ctx.evidence(rel, line, line, "java_spring.annotations"),
                        Symbol(owner, "annotation"),
                    ))

            if "@RefreshScope" in t.annotations:
                facts.append(Fact(
                    "config.refreshscope", {"class": tfqn},
                    ctx.evidence(rel, t.start, t.start, "java_spring.annotations"),
                    Symbol(tfqn, "class"),
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
                                {"channel": channel, "level": swallow_level(sw.log_method),
                                 "message": sw.message, "class": tfqn},
                                ctx.evidence(rel, sw.start, sw.end, "java_spring.annotations"),
                                Symbol(tfqn, "class"),
                            ))
                    if c.method in SAVE_METHODS and "Repository" in rtype and c.swallow:
                        # A repository save in a logged-and-swallowed catch: the write is lost
                        # silently — the DB dual of the swallowed publish above.
                        sw = c.swallow
                        facts.append(Fact(
                            "swallowed.db.failure",
                            {"repository": rtype, "level": swallow_level(sw.log_method),
                             "message": sw.message, "class": tfqn},
                            ctx.evidence(rel, sw.start, sw.end, "java_spring.annotations"),
                            Symbol(tfqn, "class"),
                        ))
                    if c.receiver == "restTemplate" or "RestTemplate" in rtype:
                        attrs = {"class": tfqn}
                        # A literal URL/path argument is the consumer-side contract anchor the
                        # OpenAPI estate join needs (NEXT-INCREMENTS §5.5 residual).
                        url = next((a for a in c.str_args
                                    if a.startswith(("http://", "https://", "/"))), None)
                        if url:
                            attrs["url"] = url
                        facts.append(Fact(
                            "http.egress", attrs,
                            ctx.evidence(rel, c.line, c.line, "java_spring.annotations"),
                            Symbol(tfqn, "class"),
                        ))
    return facts
