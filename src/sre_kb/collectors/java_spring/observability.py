"""Observability collector (logging sub-section for P1): logback pattern + MDC fields."""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol

_PATTERN = re.compile(r"<pattern>(.*?)</pattern>", re.S)
_MDC = re.compile(r"%X\{(\w+)\}")


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("logback*.xml"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        fmt = "json" if "json" in text.lower() else "pattern"
        # Emit one fact per appender pattern, not just the first — a console+file logback has two
        # <pattern> blocks and dropping the rest silently under-collected the logging config. Line
        # numbers come from the match offset so each fact cites its own block.
        for m in _PATTERN.finditer(text):
            pattern = m.group(1).strip()
            if not pattern:
                continue
            fields = _MDC.findall(pattern)
            start = text.count("\n", 0, m.start()) + 1
            end = text.count("\n", 0, m.end()) + 1
            facts.append(
                Fact(
                    "observability.logging",
                    {
                        "framework": "logback",
                        "format": fmt,
                        "pattern": pattern,
                        "correlationFields": fields,
                    },
                    ctx.evidence(rel, start, end, "java_spring.observability"),
                    Symbol("logback", "config"),
                )
            )
    return facts
