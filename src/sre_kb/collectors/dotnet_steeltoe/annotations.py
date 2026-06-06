"""C# collector: [ApiController] endpoints, Kafka producers + swallowed failures,
HttpClient egress, EF Core DbContext. Emits the same fact types as the Java collector."""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import csharp_namespace, find_line, fqn, java_type

_ROUTE = re.compile(r'\[Route\(\s*"([^"]+)"')
_HTTP = re.compile(r"\[Http(Get|Post|Put|Delete|Patch)\]")
_METHOD = re.compile(r"\b(?:public|private|protected|internal)\b[^;{=]*?\b(\w+)\s*\(")
_PRODUCE = re.compile(r"(\w+)\.ProduceAsync\(\s*\"([^\"]+)\"")
_HTTPCLIENT = re.compile(r"(?i)httpClient\.\w+Async\(")
_DBCTX = re.compile(r"\bclass\s+(\w+)\s*:\s*DbContext\b")
_LOG = re.compile(r'Log(\w+)\([^)]*?"([^"]*)"')
_HTTPMAP = {"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE", "Patch": "PATCH"}
_SKIP = {"if", "for", "while", "switch", "using", "catch", "return", "foreach", "lock"}


def _next_method(lines: list[str], idx: int) -> tuple[str, int]:
    for j in range(idx, min(idx + 8, len(lines))):
        if j > idx and lines[j].lstrip().startswith("["):
            continue
        m = _METHOD.search(lines[j])
        if m and m.group(1) not in _SKIP:
            return m.group(1), j + 1
    return "Handler", idx + 1


def _detect_swallowed(lines: list[str], idx: int) -> dict | None:
    """try/catch around a publish whose catch logs but does not rethrow (Allman or K&R)."""
    if not any("try" in lines[j] for j in range(max(0, idx - 5), idx + 1)):
        return None
    catch_idx = next((j for j in range(idx, min(idx + 6, len(lines))) if "catch" in lines[j]), None)
    if catch_idx is None:
        return None
    open_idx = next((j for j in range(catch_idx, min(catch_idx + 3, len(lines))) if "{" in lines[j]), None)
    if open_idx is None:
        return None
    depth, end = 0, open_idx
    for j in range(open_idx, min(open_idx + 16, len(lines))):
        depth += lines[j].count("{") - lines[j].count("}")
        end = j
        if depth <= 0:
            break
    body = "".join(lines[open_idx : end + 1])
    if "throw" in body:
        return None
    lm = _LOG.search(body)
    if not lm:
        return None
    return {"level": lm.group(1), "message": lm.group(2), "start": catch_idx + 1, "end": end + 1}


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.cs"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        lines = ctx.read_lines(rel)
        ns, tn = csharp_namespace(text), java_type(text)

        if "[ApiController]" in text:
            base = _ROUTE.search(text)
            base_path = base.group(1) if base else ""
            if base_path and not base_path.startswith("/"):
                base_path = "/" + base_path
            for i, line in enumerate(lines):
                hm = _HTTP.search(line)
                if not hm:
                    continue
                meth, mln = _next_method(lines, i)
                facts.append(
                    Fact(
                        "rest.endpoint",
                        {"method": _HTTPMAP[hm.group(1)], "path": base_path or "/", "handler": fqn(ns, tn, meth)},
                        ctx.evidence(rel, i + 1, mln, "dotnet_steeltoe.annotations"),
                        Symbol(fqn(ns, tn, meth), "method"),
                    )
                )

        for i, line in enumerate(lines):
            km = _PRODUCE.search(line)
            if km:
                channel = km.group(2)
                facts.append(
                    Fact(
                        "message.egress",
                        {"channel": channel, "client": km.group(1), "broker": "kafka", "class": fqn(ns, tn)},
                        ctx.evidence(rel, i + 1, i + 1, "dotnet_steeltoe.annotations"),
                        Symbol(fqn(ns, tn), "class"),
                    )
                )
                sw = _detect_swallowed(lines, i)
                if sw:
                    facts.append(
                        Fact(
                            "swallowed.failure",
                            {"channel": channel, "level": sw["level"], "message": sw["message"], "class": fqn(ns, tn)},
                            ctx.evidence(rel, sw["start"], sw["end"], "dotnet_steeltoe.annotations"),
                            Symbol(fqn(ns, tn), "class"),
                        )
                    )
            if _HTTPCLIENT.search(line):
                facts.append(
                    Fact(
                        "http.egress",
                        {"class": fqn(ns, tn)},
                        ctx.evidence(rel, i + 1, i + 1, "dotnet_steeltoe.annotations"),
                        Symbol(fqn(ns, tn), "class"),
                    )
                )

        dm = _DBCTX.search(text)
        if dm and "DbSet<" in text:
            ln = find_line(lines, "DbContext") or 1
            facts.append(
                Fact(
                    "db.repository",
                    {"name": dm.group(1)},
                    ctx.evidence(rel, ln, ln, "dotnet_steeltoe.annotations"),
                    Symbol(fqn(ns, dm.group(1)), "class"),
                )
            )
    return facts
