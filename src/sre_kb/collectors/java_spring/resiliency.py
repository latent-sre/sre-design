"""Resilience4j collector (AST-backed): @CircuitBreaker / fallbackMethod -> resiliency.*
facts. The breaker is read straight off the annotated method node, so its target and named
args (name=, fallbackMethod=) are exact regardless of formatting or other annotations."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.signatures import signature
from sre_kb.util import fqn

# Which annotation keys mark a circuit breaker comes from the shared signature library, so
# Tier-A detection and Tier-B re-derivation key off the same rule (HYBRID-PLAN §7.4).
_CB_ANNOTATIONS = signature("circuit-breaker").annotations


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        module = ctx.module(rel, "java")
        ns = module.namespace
        for t in module.types:
            for m in t.methods:
                cb = next((m.annotations[a] for a in _CB_ANNOTATIONS if a in m.annotations), None)
                if cb is None:
                    continue
                name = cb.get("name") or "cb"
                fb_name = cb.get("fallbackMethod")
                target_sym = fqn(ns, t.name, m.name)
                facts.append(Fact(
                    "resiliency.circuitbreaker",
                    {"name": name, "target": m.name, "targetSymbol": target_sym,
                     "library": "resilience4j", "fallbackMethod": fb_name},
                    ctx.evidence(rel, m.start, m.name_line, "java_spring.resiliency"),
                    Symbol(target_sym, "method"),
                ))
                if fb_name:
                    fb_method = next((x for x in t.methods if x.name == fb_name), None)
                    fb_line = fb_method.name_line if fb_method else m.name_line
                    facts.append(Fact(
                        "resiliency.fallback",
                        {"method": fb_name, "forTarget": m.name, "forName": name},
                        ctx.evidence(rel, fb_line, fb_line, "java_spring.resiliency"),
                        Symbol(fqn(ns, t.name, fb_name), "method"),
                    ))
    return facts
