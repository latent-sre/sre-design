"""R6 — observability-coverage gap-finder: fact-based refutation of metrics/logs/traces/synthetics.

The LLM proposes a missing pillar anchored on a config/build line; the engine refutes against its
OWN observability facts (a pillar the facts already prove present is dropped) and routes survivors to
review (needs-review, never auto-verified).
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.llm.gap_finder import (
    Proposal,
    collect_from_proposals,
    gap_categories,
)
from sre_kb.models.envelope import Evidence, Lines
from sre_kb.models.facts import Fact, FactSet

_POM = """\
<project>
  <dependencies>
    <dependency>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
</project>
"""
_ANCHOR = "<artifactId>spring-boot-starter-web</artifactId>"


def _ctx(tmp_path: Path) -> ScanContext:
    (tmp_path / "pom.xml").write_text(_POM, encoding="utf-8")
    return ScanContext(root=tmp_path, repo="file://x", commit=LOCAL_COMMIT)


def _ev() -> Evidence:
    return Evidence(repo="file://x", commit="0" * 40, path="pom.xml", lines=Lines(start=1, end=1),
                    excerptHash="sha256:" + "0" * 64, detector="t")


def _fs(*facts: Fact) -> FactSet:
    fs = FactSet()
    fs.add(*facts)
    return fs


def test_observability_categories_are_registered():
    assert {"missing-metrics", "missing-tracing", "missing-structured-logging",
            "missing-synthetic-monitoring"} <= gap_categories()


def test_missing_tracing_routes_when_no_tracing_dependency(tmp_path):
    ctx = _ctx(tmp_path)
    p = Proposal("missing-tracing", _ANCHOR, target="orders-api", severity="medium")
    res = collect_from_proposals(ctx, [p], fs=_fs())  # no tracing dep

    [out] = res.outcomes
    assert out.result == "routed" and res.facts                  # surfaced for review
    fact = res.facts[0]
    assert fact.attrs["category"] == "missing-tracing"
    assert fact.evidence.source_tier == "llm" and fact.evidence.path == "pom.xml"  # config-anchored


def test_missing_tracing_is_refuted_when_a_tracing_dep_is_present(tmp_path):
    ctx = _ctx(tmp_path)
    fs = _fs(Fact("tech.dependency", {"name": "spring-cloud-starter-sleuth"}, _ev()))
    res = collect_from_proposals(ctx, [Proposal("missing-tracing", _ANCHOR)], fs=fs)

    assert res.facts == []                                       # dropped — facts prove tracing present
    assert res.outcomes[0].result == "refuted"


def test_missing_metrics_is_refuted_by_actuator_or_micrometer(tmp_path):
    ctx = _ctx(tmp_path)
    for fact in (Fact("config.actuator", {"exposure": "health,prometheus"}, _ev()),
                 Fact("tech.dependency", {"name": "micrometer-registry-prometheus"}, _ev())):
        res = collect_from_proposals(ctx, [Proposal("missing-metrics", _ANCHOR)], fs=_fs(fact))
        assert res.facts == [] and res.outcomes[0].result == "refuted"


def test_missing_structured_logging_is_refuted_by_a_json_logging_fact(tmp_path):
    ctx = _ctx(tmp_path)
    fs = _fs(Fact("observability.logging", {"format": "json", "correlationFields": ["traceId"]}, _ev()))
    res = collect_from_proposals(ctx, [Proposal("missing-structured-logging", _ANCHOR)], fs=fs)
    assert res.facts == [] and res.outcomes[0].result == "refuted"


def test_missing_synthetic_monitoring_always_routes(tmp_path):
    """The engine has no synthetic-monitoring signal, so it can never refute — always to review."""
    ctx = _ctx(tmp_path)
    res = collect_from_proposals(ctx, [Proposal("missing-synthetic-monitoring", _ANCHOR)], fs=_fs())
    assert res.outcomes[0].result == "routed" and res.facts


def test_without_a_factset_observability_gaps_still_route(tmp_path):
    """The standalone path passes no fact set; an observability gap then grounds + routes (no refute)."""
    ctx = _ctx(tmp_path)
    res = collect_from_proposals(ctx, [Proposal("missing-metrics", _ANCHOR)])  # fs=None
    assert res.outcomes[0].result == "routed"
