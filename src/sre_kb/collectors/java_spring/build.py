"""Build collector: pom.xml -> tech.framework / tech.dependency facts.

Regex-based on purpose — we never invoke Maven/Gradle (no target-build execution), and
avoiding an XML parser sidesteps XXE on untrusted input.
"""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_PARENT_BOOT = re.compile(
    r"<artifactId>\s*spring-boot-starter-parent\s*</artifactId>\s*"
    r"<version>\s*([^<\s]+)\s*</version>",
    re.S,
)
_ARTIFACT = re.compile(r"<artifactId>\s*([^<\s]+)\s*</artifactId>")


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("pom.xml"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        lines = ctx.read_lines(rel)
        m = _PARENT_BOOT.search(text)
        if m:
            ln = find_line(lines, "spring-boot-starter-parent") or 1
            facts.append(
                Fact(
                    "tech.framework",
                    {"name": "spring-boot", "version": m.group(1)},
                    ctx.evidence(rel, ln, ln, "java_spring.build"),
                    Symbol("spring-boot", "framework"),
                )
            )
        seen: set[str] = set()
        for art in _ARTIFACT.finditer(text):
            name = art.group(1)
            if name in seen or name == "spring-boot-starter-parent":
                continue
            seen.add(name)
            ln = find_line(lines, f"<artifactId>{name}</artifactId>") or find_line(lines, name) or 1
            facts.append(
                Fact(
                    "tech.dependency",
                    {"name": name},
                    ctx.evidence(rel, ln, ln, "java_spring.build"),
                    Symbol(name, "dependency"),
                )
            )
    return facts
