"""Steeltoe config collector: appsettings*.json -> config.source facts (.NET parity with
the Spring `spring.config.import` detection). Steeltoe's config-server client reads
`spring:cloud:config:uri` from .NET configuration — the same external-source declaration
the Java collector mines from application.yml. .NET configuration keys are
case-insensitive, so lookup is too.

There is no .NET counterpart of `@RefreshScope` to detect (Steeltoe reloads through
IOptionsSnapshot/config providers, not an annotation) — refresh-scope stays Java-only by
design, not omission.
"""

from __future__ import annotations

import json

from sre_kb.collectors.base import ScanContext, parse_error_fact
from sre_kb.models.facts import Fact
from sre_kb.util import dig_ci, find_line

_DETECTOR = "dotnet_steeltoe.config"


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    if not ctx.files("*.csproj"):
        return facts  # self-gating: appsettings.json outside a .NET repo is someone else's
    for path in ctx.files("appsettings.json", "appsettings.*.json"):
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = json.loads(ctx.read_text(rel)) or {}
        except (json.JSONDecodeError, ValueError) as exc:
            facts.append(parse_error_fact(ctx, rel, _DETECTOR, exc))
            continue
        uri = dig_ci(data, "spring", "cloud", "config", "uri")
        if isinstance(uri, str) and uri:
            ln = find_line(lines, uri) or find_line(lines, "uri") or 1
            facts.append(Fact(
                "config.source",
                {"kind": "configserver", "uri": uri, "optional": False},
                ctx.evidence(rel, ln, ln, _DETECTOR),
            ))
    return facts
