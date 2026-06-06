"""Phase 0 trust-tier plumbing: every piece of evidence carries a `source_tier`
(defaulting to the deterministic "ast" tier), the collector protocol admits both
collector shapes, and the validation report surfaces each artifact's tier. These are
pure-plumbing guarantees — no artifact's status/confidence/content changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sre_kb.collectors.base import CollectorProtocol, ScanContext
from sre_kb.models.envelope import Artifact, Evidence, Lines, Metadata
from sre_kb.pipeline import run as run_pipeline
from sre_kb.validation import validate_doc

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
_HASH = "sha256:" + "0" * 64


def _evidence(source_tier: str | None = None) -> Evidence:
    kw = {} if source_tier is None else {"source_tier": source_tier}
    return Evidence(
        repo="r", commit="0" * 40, path="p.java",
        lines=Lines(start=1, end=1), excerptHash=_HASH, detector="d", **kw,
    )


def test_evidence_default_source_tier_is_ast() -> None:
    assert _evidence().source_tier == "ast"


def test_scan_context_stamps_ast_by_default_and_llm_on_request() -> None:
    ctx = ScanContext(root=FIXTURE, repo="file://sample")
    assert ctx.evidence("manifest.yml", 1, 1, "test").source_tier == "ast"
    assert ctx.evidence("manifest.yml", 1, 1, "test", source_tier="llm").source_tier == "llm"


def test_collector_protocol_accepts_both_shapes() -> None:
    """A file-collector (collect(ctx)) and a deriver (collect(ctx, fs)) both satisfy it."""
    from sre_kb.collectors.common import manifest_pcf  # collect(ctx)
    from sre_kb.collectors.java_spring import flow_builder  # collect(ctx, fs)

    assert isinstance(manifest_pcf.collect, CollectorProtocol)
    assert isinstance(flow_builder.collect, CollectorProtocol)


@pytest.mark.parametrize("tier", ["ast", "llm"])
def test_source_tier_serializes_and_still_validates(tier: str) -> None:
    """Both tiers serialize into evidence and the artifact still passes the envelope schema —
    keeping the pydantic model and the JSON Schema in lock-step."""
    doc = Artifact(
        kind="Flow", metadata=Metadata(name="probe"), spec={}, status="needs-review",
        evidence=[_evidence(tier)],
    ).to_doc()
    assert doc["evidence"][0]["source_tier"] == tier
    assert not any("source_tier" in e for e in validate_doc(doc))


def test_schema_rejects_unknown_tier() -> None:
    """The model is permissive (str) but the schema enum confines tiers to ast|llm."""
    doc = Artifact(
        kind="Flow", metadata=Metadata(name="probe"), spec={}, status="needs-review",
        evidence=[_evidence("bogus")],
    ).to_doc()
    assert any("source_tier" in e or "bogus" in e for e in validate_doc(doc))


@pytest.fixture(scope="module")
def report(tmp_path_factory) -> dict:
    work = tmp_path_factory.mktemp("work")
    result = run_pipeline(str(FIXTURE), work_root=str(work), run_id="tiers", to_stage="validate")
    return json.loads(result.report_path.read_text())


def test_report_exposes_tier_on_every_artifact(report: dict) -> None:
    assert report["records"], "expected the fixture to produce artifacts"
    # The deterministic AST pipeline produces only Tier-A evidence.
    assert all(rec["tier"] == "ast" for rec in report["records"])


def test_report_has_by_tier_rollup(report: dict) -> None:
    assert report["by_tier"] == {"ast": report["docs"]}
