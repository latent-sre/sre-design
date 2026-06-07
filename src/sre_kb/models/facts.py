"""Normalized, language-neutral facts emitted by collectors.

Every fact carries provenance (an envelope `Evidence`) so downstream artifacts can cite
exactly where a claim came from. Collectors produce `Fact`s; the scaffolder turns facts
into schema-tagged artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sre_kb.models.envelope import Evidence


@dataclass(frozen=True)
class Symbol:
    """A language-neutral symbol, e.g. 'com.acme.order.web.OrderController#createOrder'."""

    fqn: str
    kind: str  # class | interface | method | route | channel | config-key


@dataclass
class Fact:
    type: str  # e.g. 'rest.endpoint', 'message.egress', 'resiliency.circuitbreaker'
    attrs: dict
    evidence: Evidence
    symbol: Symbol | None = None
    # Trust tier (HYBRID-PLAN Phase 0). 'ast' = deterministic AST/config collector (default,
    # high-trust, can reach verified). 'llm' = an LLM pointer-generator proposed it and the
    # engine re-grounded it (lower-trust, can never auto-verify). The seam both tiers ride.
    source_tier: str = "ast"


@dataclass
class FactSet:
    """Container with small query helpers used by derivers and the scaffolder."""

    facts: list[Fact] = field(default_factory=list)

    def add(self, *facts: Fact) -> None:
        self.facts.extend(facts)

    def of(self, *types: str) -> list[Fact]:
        wanted = set(types)
        return [f for f in self.facts if f.type in wanted]

    def first(self, *types: str) -> Fact | None:
        found = self.of(*types)
        return found[0] if found else None
