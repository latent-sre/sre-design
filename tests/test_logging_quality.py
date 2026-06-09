"""Scaffold roll-up of parsed log statements into Observability.logging (S2 assess-logging)."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.synth.scaffold import scaffold

FIXTURE = Path(__file__).parent / "fixtures" / "sample-logging"


def _observability_doc():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-logging")
    fs = scan(ctx)
    docs = scaffold(fs, ctx)
    obs = [d for d in docs if d["kind"] == "Observability"]
    assert len(obs) == 1  # emitted from statements alone, even with no logback config
    return obs[0]


def test_logging_statements_rolled_up():
    logging = _observability_doc()["spec"]["logging"]
    assert logging["framework"] == "slf4j"   # detected from code, no logback file present
    assert logging["format"] == "default"
    stmts = logging["statements"]
    assert stmts["total"] == 3
    assert stmts["byLevel"] == {"info": 1, "error": 1, "warn": 1}
    assert stmts["loggingApis"] == ["slf4j"]
    assert stmts["parameterized"] == 2       # info + warn; the concatenated error is not


def test_alert_fatigue_signal_for_uncorrelated_error_logging():
    quality = _observability_doc()["spec"]["logging"]["quality"]
    assert quality["correlationContext"] is False        # no %X{} MDC pattern in this fixture
    assert quality["correlationFields"] == []
    assert "error-logging-without-correlation-context" in quality["alertFatigueSignals"]
    assert "non-parameterized-messages" in quality["alertFatigueSignals"]
    assert quality["placeholderHygiene"] == round(2 / 3, 4)


def test_observability_doc_is_byte_grounded():
    doc = _observability_doc()
    # the statement roll-up cites the framework import + a representative error statement
    detectors = {e["detector"] for e in doc["evidence"]}
    assert "java_spring.log_statements" in detectors
