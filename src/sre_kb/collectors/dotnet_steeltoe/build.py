"""Build collector: *.csproj -> tech.framework / tech.dependency facts (regex, no build run)."""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_TFM = re.compile(r"<TargetFrameworks?>\s*([^<\s]+)\s*</TargetFrameworks?>")  # singular or multi-target
_PKG = re.compile(r'<PackageReference\s+Include="([^"]+)"(?:[^>/]*\bVersion="([^"]+)")?')


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.csproj"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        lines = ctx.read_lines(rel)
        m = _TFM.search(text)
        if m:
            ln = find_line(lines, "TargetFramework") or 1
            version = m.group(1).split(";")[0]  # first of a multi-target list
            facts.append(
                Fact(
                    "tech.framework",
                    {"name": ".net", "version": version},
                    ctx.evidence(rel, ln, ln, "dotnet_steeltoe.build"),
                    Symbol(".net", "framework"),
                )
            )
        for pm in _PKG.finditer(text):
            name = pm.group(1)
            ln = find_line(lines, name) or 1
            attrs: dict = {"name": name}
            if pm.group(2):
                attrs["version"] = pm.group(2)
            facts.append(
                Fact(
                    "tech.dependency",
                    attrs,
                    ctx.evidence(rel, ln, ln, "dotnet_steeltoe.build"),
                    Symbol(name, "dependency"),
                )
            )
    return facts
