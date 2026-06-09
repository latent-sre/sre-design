"""Log-statement collector (S2 assess-logging, Tier-A): parse log calls + the logging API."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.java_spring import log_statements

FIXTURE = Path(__file__).parent / "fixtures" / "sample-logging"


def _facts():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-logging")
    return log_statements.collect(ctx)


def test_logging_api_detected_from_imports():
    fw = [f for f in _facts() if f.type == "observability.log.framework"]
    assert len(fw) == 1
    assert fw[0].attrs["framework"] == "slf4j"
    # cited to the slf4j import line, not the class
    line = fw[0].evidence.lines.start
    src = (FIXTURE / "src/main/java/com/acme/pay/PaymentService.java").read_text().splitlines()
    assert "import org.slf4j" in src[line - 1]


def test_each_log_statement_is_parsed_with_level_and_parameterization():
    stmts = [f for f in _facts() if f.type == "observability.log.statement"]
    by_level = sorted(f.attrs["level"] for f in stmts)
    assert by_level == ["error", "info", "warn"]  # one each, three total
    params = {f.attrs["level"]: f.attrs["parameterized"] for f in stmts}
    assert params["info"] is True and params["warn"] is True
    # the concatenated `"... " + account` ERROR has no {} placeholders -> not parameterized
    assert params["error"] is False


def test_statements_cite_their_own_call_line():
    stmts = [f for f in _facts() if f.type == "observability.log.statement"]
    assert len({f.evidence.lines.start for f in stmts}) == len(stmts)  # distinct call sites
    assert all(f.evidence.source_tier == "ast" for f in stmts)  # Tier-A, byte-grounded


def test_log_suffixed_non_logger_receiver_is_not_a_statement(tmp_path):
    # `catalog`/`backlog`/`dialog` end with "log" but are not loggers — the endswith("log")
    # receiver test misfired on exactly these and polluted the level roll-up.
    (tmp_path / "C.java").write_text(
        "package x;\nimport org.slf4j.Logger;\n"
        'class C { void m() { catalog.error("lookup-miss"); log.info("ok"); } }\n',
        encoding="utf-8",
    )
    ctx = ScanContext(root=tmp_path, repo="file://x")
    stmts = [f for f in log_statements.collect(ctx) if f.type == "observability.log.statement"]
    assert [f.attrs["level"] for f in stmts] == ["info"]  # log.info only, no catalog.error


def test_no_logging_api_means_no_statements(tmp_path):
    (tmp_path / "Plain.java").write_text(
        "package x;\npublic class Plain { void m() { System.out.println(\"hi\"); } }\n",
        encoding="utf-8",
    )
    ctx = ScanContext(root=tmp_path, repo="file://x")
    assert log_statements.collect(ctx) == []  # self-gating: no logger import -> nothing
