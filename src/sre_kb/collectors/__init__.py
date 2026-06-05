"""Deterministic collectors: scan a cloned repo into a `FactSet` with provenance.

Collectors are bounded static analyzers (regex/parse heuristics) — never executing the
target's build. File-collectors run first; derivers (flow_builder, budget_check) then
enrich the fact set.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common import manifest_pcf
from sre_kb.collectors.java_spring import (
    annotations,
    build,
    config_props,
    flow_builder,
    observability,
    resiliency,
)
from sre_kb.flow import budget_check
from sre_kb.models.facts import FactSet

# File-collectors: ctx -> list[Fact]
_FILE_COLLECTORS = [
    manifest_pcf.collect,
    build.collect,
    annotations.collect,
    config_props.collect,
    resiliency.collect,
    observability.collect,
]

# Derivers: (ctx, FactSet) -> list[Fact]
_DERIVERS = [
    flow_builder.collect,
    budget_check.collect,
]


def scan(ctx: ScanContext) -> FactSet:
    fs = FactSet()
    for collect in _FILE_COLLECTORS:
        fs.add(*collect(ctx))
    for derive in _DERIVERS:
        fs.add(*derive(ctx, fs))
    return fs
