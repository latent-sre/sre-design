"""Deterministic collectors: scan a cloned repo into a `FactSet` with provenance.

Collectors are bounded static analyzers — never executing the target's build. Code
structure (classes, methods, calls, annotations, try/catch) is read from a tree-sitter
AST (`parsing/code_model.py`, Java + C#); config files (PCF manifests, build files, YAML
properties, logback) are parsed directly. File-collectors run first; derivers
(flow_builder, budget_check) then enrich the fact set.
"""

from __future__ import annotations

from sre_kb.collectors.base import CollectorProtocol, ScanContext
from sre_kb.collectors.common import manifest_pcf, slo_catalog
from sre_kb.collectors.dotnet_steeltoe import annotations as dotnet_annotations
from sre_kb.collectors.dotnet_steeltoe import build as dotnet_build
from sre_kb.collectors.dotnet_steeltoe import resiliency as dotnet_resiliency
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
_FILE_COLLECTORS: list[CollectorProtocol] = [
    manifest_pcf.collect,
    slo_catalog.collect,
    build.collect,
    annotations.collect,
    config_props.collect,
    resiliency.collect,
    observability.collect,
    # .NET / Steeltoe (self-gating: no *.cs/*.csproj -> emit nothing)
    dotnet_build.collect,
    dotnet_annotations.collect,
    dotnet_resiliency.collect,
]

# Derivers: (ctx, FactSet) -> list[Fact]
_DERIVERS: list[CollectorProtocol] = [
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
