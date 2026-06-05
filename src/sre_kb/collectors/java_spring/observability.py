"""Observability collector (logging sub-section for P1): logback pattern + MDC fields."""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_PATTERN = re.compile(r"<pattern>(.*?)</pattern>", re.S)
_MDC = re.compile(r"%X\{(\w+)\}")


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("logback*.xml"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        lines = ctx.read_lines(rel)
        m = _PATTERN.search(text)
        if not m:
            continue
        pattern = m.group(1).strip()
        fields = _MDC.findall(pattern)
        fmt = "json" if "json" in text.lower() else "pattern"
        start = find_line(lines, "<pattern>") or 1
        end = find_line(lines, "</pattern>") or start
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
