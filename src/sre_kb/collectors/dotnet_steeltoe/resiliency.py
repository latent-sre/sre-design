"""C# resiliency collector (AST-backed): Polly circuit breaker + fallback.

The breaker's protected method is the one that actually invokes the breaker field (found
via the AST), not the next textual method — robust to ctor/DI/field-initializer registration.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.parsing import parse
from sre_kb.util import fqn


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.cs"):
        rel = ctx.rel(path)
        module = parse("csharp", ctx.read_text(rel))
        ns = module.namespace
        for t in module.types:
            cb_lines = [c.line for m in t.methods for c in m.calls if "CircuitBreaker" in c.method]
            if not cb_lines:
                continue
            breaker = next((fn for fn, ft in t.fields.items() if "CircuitBreaker" in ft), None)
            target, target_line = None, 0
            if breaker:
                for m in t.methods:
                    if any(c.receiver == breaker for c in m.calls):
                        target, target_line = m.name, m.name_line
                        break
            if not target:
                m = next((m for m in t.methods if m.name != t.name and not m.name.endswith("Fallback")), None)
                target, target_line = (m.name, m.name_line) if m else ("method", cb_lines[0])

            name = t.name[:-6].lower() if t.name.endswith("Client") else t.name.lower()
            target_sym = fqn(ns, t.name, target)
            start, end = sorted((cb_lines[0], target_line or cb_lines[0]))
            facts.append(Fact(
                "resiliency.circuitbreaker",
                {"name": name, "target": target, "targetSymbol": target_sym,
                 "library": "polly", "fallbackMethod": None},
                ctx.evidence(rel, start, end, "dotnet_steeltoe.resiliency"),
                Symbol(target_sym, "method"),
            ))
            fb = next((m for m in t.methods if m.name.endswith("Fallback")), None)
            if fb:
                facts.append(Fact(
                    "resiliency.fallback",
                    {"method": fb.name, "forTarget": target, "forName": name},
                    ctx.evidence(rel, fb.name_line, fb.name_line, "dotnet_steeltoe.resiliency"),
                    Symbol(fqn(ns, t.name, fb.name), "method"),
                ))
    return facts
