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


def test_fan_out_cap_blocks_runaway_tree(tmp_path):
    """A runaway artifact count is refused before any tree is assembled."""
    from sre_kb.publish import assemble_pr
    from sre_kb.publish.forge import ForgePublishError
    from sre_kb.workspace import RunLayout

    layout = RunLayout(tmp_path, "cap")
    docs = [{"kind": "Flow", "metadata": {"name": f"f{i}", "service": "s"}, "spec": {}, "status": "verified"}
            for i in range(5)]
    with pytest.raises(ForgePublishError):
        assemble_pr(layout, docs, None, dry_run=True, max_artifacts=2)


def test_publish_reassembly_preserves_human_edit(tmp_path):
    first = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="preserve", to_stage="publish")
    base = first.pr / "catalog" / "order-service"
    review = base / "REVIEW.md"
    human = review.read_text(encoding="utf-8") + "\nmanual note\n"
    review.write_text(human, encoding="utf-8")

    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="preserve", to_stage="publish")

    assert review.read_text(encoding="utf-8") == human
    assert (base / ".proposed" / "REVIEW.md").is_file()


def test_manifest_merge_prunes_only_ai_owned_orphans(tmp_path):
    from sre_kb.publish.manifest import merge_tree

    dest = tmp_path / "dest"
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "generated.md").write_text("v1\n", encoding="utf-8")
    merge_tree(stage, dest)
    assert (dest / "generated.md").is_file()

    empty = tmp_path / "empty"
    empty.mkdir()
    merge_tree(empty, dest)
    assert not (dest / "generated.md").exists()

    (stage / "generated.md").write_text("v2\n", encoding="utf-8")
    merge_tree(stage, dest)
    (dest / "generated.md").write_text("human edit\n", encoding="utf-8")
    merge_tree(empty, dest)
    assert (dest / "generated.md").read_text(encoding="utf-8") == "human edit\n"


def test_manifest_merge_routes_diverged_file_to_proposed(tmp_path):
    from sre_kb.publish.manifest import merge_tree

    dest = tmp_path / "dest"
    stage = tmp_path / "stage"
    stage.mkdir()
    generated = stage / "runbooks" / "r.md"
    generated.parent.mkdir()
    generated.write_text("v1\n", encoding="utf-8")
    merge_tree(stage, dest)

    (dest / "runbooks" / "r.md").write_text("human edit\n", encoding="utf-8")
    generated.write_text("v2\n", encoding="utf-8")
    merge_tree(stage, dest)

    assert (dest / "runbooks" / "r.md").read_text(encoding="utf-8") == "human edit\n"
    assert (dest / ".proposed" / "runbooks" / "r.md").read_text(encoding="utf-8") == "v2\n"
