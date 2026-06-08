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


@dataclass
class FactSet:
    """Container with small query helpers used by derivers and the scaffolder."""

    facts: list[Fact] = field(default_factory=list)
    _index: dict[str, list[Fact]] | None = field(default=None, repr=False, compare=False)

    def add(self, *facts: Fact) -> None:
        self.facts.extend(facts)
        self._index = None  # invalidate the type index; rebuilt lazily on next query

    def _by_type(self) -> dict[str, list[Fact]]:
        if self._index is None:
            idx: dict[str, list[Fact]] = {}
            for f in self.facts:  # insertion order preserved per type
                idx.setdefault(f.type, []).append(f)
            self._index = idx
        return self._index

    def of(self, *types: str) -> list[Fact]:
        if len(types) == 1:  # the common case: O(k) on the indexed bucket, not O(n) over all facts
            return list(self._by_type().get(types[0], ()))
        wanted = set(types)
        return [f for f in self.facts if f.type in wanted]  # multi-type keeps global fact order

    def first(self, *types: str) -> Fact | None:
        found = self.of(*types)
        return found[0] if found else None
