"""Tier-B map-api-contracts re-grounding (coverage #7 versioning): the engine locates a semantic-break
proposal, refutes anything the deterministic diff already covers structurally, and routes survivors to
review — the non-circular contract, applied to API versioning."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.pipeline import contract
from sre_kb.tiers import LLM

FIXTURE = Path(__file__).parent / "fixtures" / "sample-api"


def _result():
    return contract.run_map_contracts(str(FIXTURE))


def test_genuine_semantic_break_is_routed_to_review_and_grounded():
    res = _result()
    routed = [o for o in res.outcomes if o.result == "routed"]
    assert len(routed) == 1
    o = routed[0]
    assert o.proposal.target == "GET /api/v1/orders"
    assert o.path == "openapi.yaml" and o.lines is not None
    # Routed survivors are stamped Tier-B (never auto-verified) and carry a hash-checkable citation.
    assert o.evidence is not None and o.evidence.source_tier == LLM
    assert o.evidence.path == "openapi.yaml"


def test_proposal_duplicating_a_structural_change_is_refuted():
    # GET /api/v1/orders/{id} is `operation-added` in the deterministic diff — not a semantic break.
    res = _result()
    refuted = next(o for o in res.outcomes if o.result == "refuted")
    assert refuted.proposal.target == "GET /api/v1/orders/{id}"
    assert "structural change" in refuted.note


def test_unlocatable_anchor_is_dropped():
    res = _result()
    missing = next(o for o in res.outcomes if o.result == "unlocatable")
    assert missing.proposal.anchor == "format: epoch-millis"
    assert missing.path is None


def test_kept_and_dropped_partition_the_outcomes():
    res = _result()
    assert len(res.kept()) == 1
    assert len(res.dropped()) == 2
    assert len(res.kept()) + len(res.dropped()) == len(res.outcomes)


def test_no_proposals_file_is_a_clean_no_op(tmp_path):
    (tmp_path / "openapi.yaml").write_text(
        'openapi: 3.0.3\ninfo: {title: T, version: "1.0.0"}\npaths: {}\n', encoding="utf-8")
    assert contract.run_map_contracts(str(tmp_path)).outcomes == []


def test_locator_never_points_at_the_baseline_spec(tmp_path):
    # An anchor present only in the baseline (not the current spec) must not locate — a semantic
    # break is about the NEW contract.
    base = ('openapi: 3.0.3\ninfo: {title: T, version: "1.0.0"}\npaths:\n'
            '  /things:\n    get:\n      operationId: onlyInBaseline\n'
            '      responses: {"200": {description: ok}}\n')
    cur = ('openapi: 3.0.3\ninfo: {title: T, version: "1.0.0"}\npaths:\n'
           '  /things:\n    get:\n      responses: {"200": {description: ok}}\n')
    (tmp_path / ".sre" / "api-baseline").mkdir(parents=True)
    (tmp_path / ".sre" / "api-baseline" / "openapi.yaml").write_text(base, encoding="utf-8")
    (tmp_path / "openapi.yaml").write_text(cur, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    assert contract._locate_in_current_spec(ctx, "operationId: onlyInBaseline") is None


def test_malformed_proposals_file_self_gates(tmp_path):
    (tmp_path / "openapi.yaml").write_text(
        'openapi: 3.0.3\ninfo: {title: T, version: "1.0.0"}\npaths: {}\n', encoding="utf-8")
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "contract-proposals.json").write_text("{ not json", encoding="utf-8")
    assert contract.run_map_contracts(str(tmp_path)).outcomes == []
