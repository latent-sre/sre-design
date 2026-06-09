"""S2 Tier-B: logging-quality gap categories in the gap-finder.

`missing-log-context` refutes against the engine's own logging facts (global correlation context);
`noisy-error-logging` is a judgment call routed to review. Both ride the non-circular contract:
the LLM points at a verbatim log line, the engine locates + judges, nothing auto-verifies.
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.llm import gap_finder
from sre_kb.collectors.llm.gap_finder import Proposal
from sre_kb.models.facts import Fact, FactSet, Symbol

FIXTURE = Path(__file__).parent / "fixtures" / "sample-logging"
_ANCHOR_ERROR = 'log.error("invalid amount for account " + account);'
_ANCHOR_WARN = 'log.warn("charge retry for account={}", account, e);'


def _ctx():
    return ScanContext(root=FIXTURE, repo="file://sample-logging")


def _logging_fact(*, correlation: bool) -> FactSet:
    fs = FactSet()
    fs.add(Fact(
        "observability.logging",
        {"framework": "logback", "format": "pattern",
         "correlationFields": ["traceId"] if correlation else []},
        _ctx().evidence("src/main/java/com/acme/pay/PaymentService.java", 1, 1, "x"),
        Symbol("logback", "config"),
    ))
    return fs


def test_logging_categories_are_registered():
    cats = gap_finder.gap_categories()
    assert {"noisy-error-logging", "missing-log-context"} <= cats


def test_noisy_error_logging_routes_to_review():
    res = gap_finder.collect_from_proposals(
        _ctx(), [Proposal("noisy-error-logging", _ANCHOR_ERROR, target="payment-service")])
    assert len(res.facts) == 1                       # routed survivor became a fact
    fact = res.facts[0]
    assert fact.attrs["category"] == "noisy-error-logging"
    assert fact.attrs["rederivation"] == "judgment"
    assert fact.evidence.source_tier == "llm"        # Tier-B, never auto-verifies
    assert res.kept() and res.kept()[0].result == "routed"


def test_missing_log_context_refuted_when_correlation_present():
    res = gap_finder.collect_from_proposals(
        _ctx(), [Proposal("missing-log-context", _ANCHOR_WARN)],
        fs=_logging_fact(correlation=True))
    assert res.facts == []                            # global %X{traceId} refutes the gap
    assert res.outcomes[0].result == "refuted"


def test_missing_log_context_routes_when_no_correlation():
    res = gap_finder.collect_from_proposals(
        _ctx(), [Proposal("missing-log-context", _ANCHOR_WARN)],
        fs=_logging_fact(correlation=False))
    assert len(res.facts) == 1                         # no context -> routed to review
    assert res.facts[0].evidence.source_tier == "llm"


def test_unlocatable_logging_anchor_is_dropped():
    res = gap_finder.collect_from_proposals(
        _ctx(), [Proposal("noisy-error-logging", "log.error(\"not in this repo verbatim\");")])
    assert res.facts == []
    assert res.outcomes[0].result == "unlocatable"
