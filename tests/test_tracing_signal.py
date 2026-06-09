"""Shared tracing-dependency signal (R6): readiness `tracing-enabled` + gap-finder refutation agree."""

from __future__ import annotations

from sre_kb.collectors.llm.gap_finder import _observability_present
from sre_kb.inventory_signatures import is_tracing_dependency
from sre_kb.models.envelope import Evidence, Lines
from sre_kb.models.facts import Fact, FactSet, Symbol
from sre_kb.scoring.readiness import readiness_spec


def test_is_tracing_dependency_matches_known_libraries():
    assert is_tracing_dependency("spring-cloud-starter-sleuth")
    assert is_tracing_dependency("opentelemetry-api")
    assert is_tracing_dependency("micrometer-tracing-bridge-otel")
    assert is_tracing_dependency("brave-instrumentation-http")
    assert not is_tracing_dependency("micrometer-registry-prometheus")
    assert not is_tracing_dependency("spring-boot-starter-web")


def _ev() -> Evidence:
    return Evidence(repo="x", commit="0" * 40, path="pom.xml", lines=Lines(start=1, end=1),
                    excerptHash="sha256:" + "0" * 64, detector="t")


def _fs_with_dep(name: str | None) -> FactSet:
    fs = FactSet()
    if name:
        fs.add(Fact("tech.dependency", {"name": name}, _ev(), Symbol(name, "dep")))
    return fs


def test_readiness_tracing_enabled_tracks_the_dependency():
    on = readiness_spec(_fs_with_dep("spring-cloud-starter-sleuth"), [], [])
    assert on["prrChecks"]["tracing-enabled"] is True
    assert "No distributed tracing (Sleuth/OTel) detected" not in on["gaps"]
    off = readiness_spec(_fs_with_dep(None), [], [])
    assert off["prrChecks"]["tracing-enabled"] is False
    assert "No distributed tracing (Sleuth/OTel) detected" in off["gaps"]


def test_gap_finder_refutation_agrees_with_readiness():
    # the same dependency that flips readiness on must refute a missing-tracing gap (one source of truth)
    assert _observability_present(_fs_with_dep("opentelemetry-sdk"), "missing-tracing") is True
    assert _observability_present(_fs_with_dep(None), "missing-tracing") is False
