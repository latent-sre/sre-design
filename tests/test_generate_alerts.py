"""Tier-B generate-alerts re-grounding (coverage #19): the engine drafts a needs-review log-pattern
Alert only from a grounded error/warn log line, refusing info/debug by level and any anchor it can't
locate — the non-circular contract applied to alert authoring."""

from __future__ import annotations

from pathlib import Path

from sre_kb.pipeline import alerts_draft
from sre_kb.pipeline.alerts_draft import AlertProposal, run_generate_alerts
from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.tiers import LLM
from sre_kb.validation.provenance import verify_evidence
from sre_kb.validation.structural import validate_doc

FIXTURE = Path(__file__).parent / "fixtures" / "sample-logging"


def _result():
    return run_generate_alerts(str(FIXTURE))


def test_error_log_line_is_drafted_as_a_needs_review_alert():
    res = _result()
    routed = [o for o in res.outcomes if o.result == "routed"]
    assert len(routed) == 1 and routed[0].line == 17        # the ERROR line
    assert len(res.docs) == 1
    doc = res.docs[0]
    assert doc["kind"] == "Alert" and doc["status"] == "needs-review"
    assert doc["spec"]["signalSource"] == "log-pattern"
    # The query is engine-derived from the byte-grounded message literal, not LLM-supplied.
    assert "invalid amount for account" in doc["spec"]["expr"]["splunk"]
    assert doc["spec"]["severity"] == "high"


def test_drafted_alert_is_fenced_tier_b_and_byte_grounded():
    doc = _result().docs[0]
    assert doc["evidence"][0]["source_tier"] == LLM
    assert doc["provenanceMode"] == "llm-asserted"
    assert doc["unverifiedAgainstLive"] is True
    assert validate_doc(doc) == []                          # schema-valid
    assert verify_evidence(doc, FIXTURE.resolve()) == []    # the cited bytes hash-check


def test_info_log_line_is_refuted_by_level():
    refuted = next(o for o in _result().outcomes if o.result == "refuted")
    assert refuted.line == 13                               # the INFO line
    assert "info" in refuted.note


def test_unlocatable_anchor_is_dropped():
    missing = next(o for o in _result().outcomes if o.result == "unlocatable")
    assert missing.path is None


def test_kept_and_dropped_partition_the_outcomes():
    res = _result()
    assert len(res.kept()) == 1 and len(res.dropped()) == 2
    assert len(res.kept()) + len(res.dropped()) == len(res.outcomes)


def test_warn_line_routes_and_defaults_to_medium_severity():
    # A warn line with no proposed severity defaults to medium and still drafts an alert.
    ctx = ScanContext(root=FIXTURE, repo="file://sample-logging")
    fs = scan(ctx)
    p = AlertProposal(anchor='log.warn("charge retry for account={}", account, e);')
    res = alerts_draft.reground(ctx, [p], fs, "sample-logging")
    assert [o.result for o in res.outcomes] == ["routed"]
    assert res.docs[0]["spec"]["severity"] == "medium"
    assert "charge retry for account=" in res.docs[0]["spec"]["expr"]["splunk"]


def test_anchor_without_a_parsed_log_statement_is_unconfirmable():
    # An anchor that locates but isn't a log call has nothing to ground the alert on.
    ctx = ScanContext(root=FIXTURE, repo="file://sample-logging")
    fs = scan(ctx)
    p = AlertProposal(anchor="private Gateway gateway() {")
    res = alerts_draft.reground(ctx, [p], fs, "sample-logging")
    assert [o.result for o in res.outcomes] == ["unconfirmable"]
    assert not res.docs


def test_no_proposals_file_is_a_clean_no_op(tmp_path):
    (tmp_path / "C.java").write_text("class C {}\n", encoding="utf-8")
    res = run_generate_alerts(str(tmp_path))
    assert res.outcomes == [] and res.docs == []


def test_malformed_proposals_file_self_gates(tmp_path):
    (tmp_path / "C.java").write_text("class C {}\n", encoding="utf-8")
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "alert-proposals.json").write_text("{ not json", encoding="utf-8")
    assert run_generate_alerts(str(tmp_path)).outcomes == []
