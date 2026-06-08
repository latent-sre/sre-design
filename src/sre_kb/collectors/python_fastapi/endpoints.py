"""Python / FastAPI collector (AST-backed) — first breadth slice for a third stack.

Emits the same normalized facts the Java/.NET collectors do, so the existing scaffolder produces
the same KB kinds (Interface, Architecture, TechStack, ...) for a Python service — proving
repo-neutrality beyond the JVM/CLR. Scope of this slice: REST endpoints (FastAPI route decorators),
outbound HTTP egress (httpx/requests), and the tech stack (framework + runtime + deps). Flow
correlation, resiliency, and swallow detection for Python are follow-ups.

Self-gating: a target with no `*.py` files emits nothing.
"""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "options", "head"}
# Outbound HTTP clients whose <receiver>.<verb>(...) is a dependency call. Only unambiguous HTTP
# client modules — NOT generic names like `client`/`session`, which also name DB/ORM sessions, cache
# clients, and message clients and produced false `http.egress` facts. (Python locals aren't
# type-resolved here, so a `client = httpx.Client()` alias is a known recall gap, not a false hit.)
_EGRESS_RECEIVERS = {"httpx", "requests", "aiohttp"}
_EGRESS_METHODS = _HTTP_VERBS | {"request", "send"}
_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)")


def _deps(ctx: ScanContext) -> list[tuple[str, str, int]]:
    """(name, relpath, line) for each requirements.txt dependency."""
    out: list[tuple[str, str, int]] = []
    for path in ctx.files("requirements.txt", "requirements-*.txt"):
        rel = ctx.rel(path)
        for i, line in enumerate(ctx.read_lines(rel), 1):
            s = line.strip()
            if not s or s.startswith(("#", "-")):
                continue
            m = _REQ_LINE.match(s)
            if m:
                out.append((m.group(1), rel, i))
    return out


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    py_files = ctx.files("*.py")
    if not py_files:
        return facts

    framework_done = False
    for path in py_files:
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        module = ctx.module(rel, "python")
        for t in module.types:
            for m in t.methods:
                for ann, args in m.annotations.items():
                    verb = ann.rsplit(".", 1)[-1].lower()  # "app.get" / "router.get" -> "get"
                    if verb in _HTTP_VERBS and args.get(""):
                        facts.append(Fact(
                            "rest.endpoint",
                            {"method": verb.upper(), "path": args[""], "handler": m.name},
                            ctx.evidence(rel, m.start, m.name_line, "python_fastapi.endpoints"),
                            Symbol(m.name, "method"),
                        ))
                for c in m.calls:
                    if c.method.lower() in _EGRESS_METHODS and c.receiver.lower() in _EGRESS_RECEIVERS:
                        facts.append(Fact(
                            "http.egress",
                            {"class": f"{rel}#{m.name}", "client": c.receiver},
                            ctx.evidence(rel, c.line, c.line, "python_fastapi.endpoints"),
                            Symbol(m.name, "method"),
                        ))

        if not framework_done and re.search(r"(?m)^\s*(from|import)\s+fastapi\b", text):
            ln = find_line(ctx.read_lines(rel), "fastapi") or 1
            ev = ctx.evidence(rel, ln, ln, "python_fastapi.endpoints")
            build_tool = "pip" if ctx.files("requirements.txt", "requirements-*.txt") else (
                "poetry" if ctx.files("pyproject.toml") else None)
            facts.append(Fact("tech.framework", {"name": "fastapi"}, ev, Symbol("fastapi", "framework")))
            facts.append(Fact(
                "tech.runtime",
                {"language": "python", "runtime": "cpython", "buildTool": build_tool},
                ev, Symbol("python", "runtime"),
            ))
            framework_done = True

    for name, rel, ln in _deps(ctx):
        facts.append(Fact(
            "tech.dependency", {"name": name},
            ctx.evidence(rel, ln, ln, "python_fastapi.endpoints"), Symbol(name, "dependency"),
        ))
    return facts
