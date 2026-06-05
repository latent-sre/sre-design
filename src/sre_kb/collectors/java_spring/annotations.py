"""Spring annotation collector: REST endpoints, message publishers, repositories,
HTTP egress, and swallowed-failure detection (the seed for Alerts/Runbooks).

Bounded heuristics on purpose (no full Java parse); unresolved structure is simply not
emitted rather than guessed.
"""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line, fqn, java_package, java_type

_MAPPING = re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping(?:\(([^)]*)\))?")
_CLASS_REQ_MAPPING = re.compile(r'@RequestMapping\(\s*(?:value\s*=\s*)?(?:\{\s*)?"([^"]+)"')
_STR = re.compile(r'"([^"]+)"')
_METHOD_DECL = re.compile(r"\b(?:public|private|protected)\b[^;{=]*?\b(\w+)\s*\(")
_KAFKA_SEND = re.compile(r"(\w+)\.send\(\s*\"([^\"]+)\"")
_RESTTEMPLATE = re.compile(r"\brestTemplate\.(\w+)\(")
_JPA = re.compile(r"\binterface\s+(\w+)\s+extends\s+[\w<>,\s]*JpaRepository")
_LOG = re.compile(r'log\.(\w+)\(\s*"([^"]*)"')

_HTTP = {"Get": "GET", "Post": "POST", "Put": "PUT", "Delete": "DELETE", "Patch": "PATCH"}


def _next_method(lines: list[str], idx: int) -> tuple[str, int]:
    for j in range(idx, min(idx + 8, len(lines))):
        if j > idx and lines[j].lstrip().startswith("@"):
            continue
        m = _METHOD_DECL.search(lines[j])
        if m:
            return m.group(1), j + 1
    return "handler", idx + 1


def _detect_swallowed(lines: list[str], send_idx: int) -> dict | None:
    """A try/catch around a publish whose catch logs but does not rethrow = data-loss risk."""
    if not any("try" in lines[j] for j in range(max(0, send_idx - 4), send_idx + 1)):
        return None
    catch_idx = next(
        (j for j in range(send_idx, min(send_idx + 5, len(lines))) if "catch" in lines[j]),
        None,
    )
    if catch_idx is None:
        return None
    depth, end = 1, catch_idx
    for j in range(catch_idx + 1, min(catch_idx + 14, len(lines))):
        depth += lines[j].count("{") - lines[j].count("}")
        end = j
        if depth <= 0:
            break
    body = "".join(lines[catch_idx + 1 : end + 1])
    if "throw" in body:
        return None
    lm = _LOG.search(body)
    if not lm:
        return None
    return {"level": lm.group(1), "message": lm.group(2), "start": catch_idx + 1, "end": end + 1}


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        lines = ctx.read_lines(rel)
        pkg, tn = java_package(text), java_type(text)

        if "@RestController" in text:
            base = _CLASS_REQ_MAPPING.search(text)
            base_path = base.group(1) if base else ""
            for i, line in enumerate(lines):
                mm = _MAPPING.search(line)
                if not mm:
                    continue
                http = _HTTP[mm.group(1)]
                sub = ""
                if mm.group(2):
                    sm = _STR.search(mm.group(2))
                    sub = sm.group(1) if sm else ""
                meth, mln = _next_method(lines, i)
                facts.append(
                    Fact(
                        "rest.endpoint",
                        {"method": http, "path": (base_path + sub) or "/", "handler": fqn(pkg, tn, meth)},
                        ctx.evidence(rel, i + 1, mln, "java_spring.annotations"),
                        Symbol(fqn(pkg, tn, meth), "method"),
                    )
                )

        for i, line in enumerate(lines):
            km = _KAFKA_SEND.search(line)
            if km:
                channel = km.group(2)
                facts.append(
                    Fact(
                        "message.egress",
                        {"channel": channel, "client": km.group(1), "broker": "kafka", "class": fqn(pkg, tn)},
                        ctx.evidence(rel, i + 1, i + 1, "java_spring.annotations"),
                        Symbol(fqn(pkg, tn), "class"),
                    )
                )
                sw = _detect_swallowed(lines, i)
                if sw:
                    facts.append(
                        Fact(
                            "swallowed.failure",
                            {"channel": channel, "level": sw["level"], "message": sw["message"], "class": fqn(pkg, tn)},
                            ctx.evidence(rel, sw["start"], sw["end"], "java_spring.annotations"),
                            Symbol(fqn(pkg, tn), "class"),
                        )
                    )
            if _RESTTEMPLATE.search(line):
                facts.append(
                    Fact(
                        "http.egress",
                        {"class": fqn(pkg, tn)},
                        ctx.evidence(rel, i + 1, i + 1, "java_spring.annotations"),
                        Symbol(fqn(pkg, tn), "class"),
                    )
                )

        jm = _JPA.search(text)
        if jm:
            ln = find_line(lines, "JpaRepository") or 1
            facts.append(
                Fact(
                    "db.repository",
                    {"name": jm.group(1)},
                    ctx.evidence(rel, ln, ln, "java_spring.annotations"),
                    Symbol(fqn(pkg, jm.group(1)), "interface"),
                )
            )
    return facts
