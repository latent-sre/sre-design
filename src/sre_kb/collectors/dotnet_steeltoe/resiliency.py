"""C# resiliency collector: Polly circuit breaker + fallback -> resiliency.* facts."""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import csharp_namespace, fqn, java_type

_CB_CALL = re.compile(r"CircuitBreaker\w*\(")
_CB_VAR = re.compile(r"(\w+)\s*=\s*[^=;]*CircuitBreaker")  # the breaker's variable/field name
_METHOD = re.compile(r"\bpublic\b[^;{=]*?\b(\w+)\s*\(")
_FALLBACK = re.compile(r"\b(?:public|private)\b[^;{=]*?\b(\w*Fallback)\s*\(")
_SKIP = {"if", "for", "while", "switch", "using", "catch", "return"}


def _next_public(lines: list[str], idx: int) -> tuple[str, int]:
    for j in range(idx, min(idx + 14, len(lines))):
        m = _METHOD.search(lines[j])
        if m and m.group(1) not in _SKIP:
            return m.group(1), j + 1
    return "method", idx + 1


def _method_using(lines: list[str], token: str) -> tuple[str | None, int]:
    """Public method whose body invokes `token` (e.g. `_breaker.`) — the protected method,
    regardless of where the breaker is declared (ctor / DI / field initializer)."""
    current, cline = None, 0
    for i, line in enumerate(lines):
        m = _METHOD.search(line)
        if m and m.group(1) not in _SKIP:
            current, cline = m.group(1), i + 1
        elif current and token in line:
            return current, cline
    return None, 0


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.cs"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        if "CircuitBreaker" not in text:
            continue
        lines = ctx.read_lines(rel)
        ns, tn = csharp_namespace(text), java_type(text)
        cb_idx = next((i for i, line in enumerate(lines) if _CB_CALL.search(line)), None)
        if cb_idx is None:
            continue
        name = tn[:-6].lower() if tn.endswith("Client") else tn.lower()
        # Prefer the method that actually invokes the breaker; fall back to textual scan.
        var_m = _CB_VAR.search(lines[cb_idx])
        target, mln = (None, 0)
        if var_m:
            target, mln = _method_using(lines, f"{var_m.group(1)}.")
        if not target:
            target, mln = _next_public(lines, cb_idx)
        start, end = sorted((cb_idx + 1, mln))
        facts.append(
            Fact(
                "resiliency.circuitbreaker",
                {"name": name, "target": target, "targetSymbol": fqn(ns, tn, target),
                 "library": "polly", "fallbackMethod": None},
                ctx.evidence(rel, start, end, "dotnet_steeltoe.resiliency"),
                Symbol(fqn(ns, tn, target), "method"),
            )
        )
        for i, line in enumerate(lines):
            fm = _FALLBACK.search(line)
            if fm:
                facts.append(
                    Fact(
                        "resiliency.fallback",
                        {"method": fm.group(1), "forTarget": target, "forName": name},
                        ctx.evidence(rel, i + 1, i + 1, "dotnet_steeltoe.resiliency"),
                        Symbol(fqn(ns, tn, fm.group(1)), "method"),
                    )
                )
                break
    return facts
