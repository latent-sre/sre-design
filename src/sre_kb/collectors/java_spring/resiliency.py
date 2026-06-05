"""Resilience4j collector: @CircuitBreaker / fallbackMethod -> resiliency.* facts."""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line, fqn, java_package, java_type

_CB = re.compile(r"@CircuitBreaker\(([^)]*)\)")
_NAME = re.compile(r'name\s*=\s*"([^"]+)"')
_FALLBACK = re.compile(r'fallbackMethod\s*=\s*"([^"]+)"')
_METHOD_DECL = re.compile(r"\b(?:public|private|protected)\b[^;{=]*?\b(\w+)\s*\(")


def _next_method(lines: list[str], idx: int) -> tuple[str, int]:
    for j in range(idx, min(idx + 8, len(lines))):
        if j > idx and lines[j].lstrip().startswith("@"):
            continue
        m = _METHOD_DECL.search(lines[j])
        if m:
            return m.group(1), j + 1
    return "method", idx + 1


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        if "@CircuitBreaker" not in text:
            continue
        lines = ctx.read_lines(rel)
        pkg, tn = java_package(text), java_type(text)
        for i, line in enumerate(lines):
            cm = _CB.search(line)
            if not cm:
                continue
            args = cm.group(1)
            name = (_NAME.search(args).group(1) if _NAME.search(args) else "cb")
            fb = _FALLBACK.search(args)
            meth, mln = _next_method(lines, i)
            facts.append(
                Fact(
                    "resiliency.circuitbreaker",
                    {
                        "name": name,
                        "target": meth,
                        "targetSymbol": fqn(pkg, tn, meth),
                        "library": "resilience4j",
                        "fallbackMethod": fb.group(1) if fb else None,
                    },
                    ctx.evidence(rel, i + 1, mln, "java_spring.resiliency"),
                    Symbol(fqn(pkg, tn, meth), "method"),
                )
            )
            if fb:
                fbname = fb.group(1)
                fbln = find_line(lines, fbname + "(") or mln
                facts.append(
                    Fact(
                        "resiliency.fallback",
                        {"method": fbname, "forTarget": meth, "forName": name},
                        ctx.evidence(rel, fbln, fbln, "java_spring.resiliency"),
                        Symbol(fqn(pkg, tn, fbname), "method"),
                    )
                )
    return facts
