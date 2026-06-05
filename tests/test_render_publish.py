"""Render + publish (dry-run): the KB projects to Copilot guardrails, Mermaid diagrams,
runbooks, a Backstage catalog, and a staged per-service PR tree — all offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from sre_kb.pipeline import run as run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp("work")
    return run_pipeline(str(FIXTURE), work_root=str(work), run_id="p", to_stage="publish")


def test_projections_and_pr_exist(result):
    assert result.projections and result.projections.exists()
    assert result.pr and result.pr.exists()


def test_copilot_reliability_guardrails(result):
    ci = (result.projections / ".github" / "copilot-instructions.md").read_text()
    assert "Reliability guardrails" in ci
    assert "circuit breaker" in ci.lower()
    assert "swallow" in ci.lower()  # the data-loss guardrail


def test_runbook_embeds_mermaid(result):
    runbooks = list((result.projections / "runbooks").glob("*.md"))
    assert runbooks
    assert "```mermaid" in runbooks[0].read_text()


def test_pr_tree_structure(result):
    base = result.pr / "catalog" / "order-service"
    assert (base / "REVIEW.md").exists()
    assert (base / "catalog-info.yaml").exists()
    assert (base / ".github" / "copilot-instructions.md").exists()
    assert (base / "kb").exists()


def test_review_flags_needs_review(result):
    review = (result.pr / "catalog" / "order-service" / "REVIEW.md").read_text()
    assert "Alert/order-created-publish-failures" in review
