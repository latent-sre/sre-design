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


def test_single_service_topology_renders(result):
    mmd = (result.projections / "diagrams" / "order-service-topology.mmd").read_text()
    assert mmd.startswith("graph LR")
    assert "orders-postgres" in mmd  # the bound datastore is drawn without an estate sweep
    assert "classDef datastore" in mmd  # typed nodes carry the engine's fixed styling


def test_diagrams_get_github_renderable_wrappers(result):
    topo_md = (result.projections / "diagrams" / "order-service-topology.md").read_text()
    assert "```mermaid" in topo_md and "Legend:" in topo_md
    flow_md = (result.projections / "diagrams" / "create-order.md").read_text()
    assert "```mermaid" in flow_md


def test_pr_tree_structure(result):
    # per-service content lives under the Backstage catalog path
    base = result.pr / "catalog" / "order-service"
    assert (base / "REVIEW.md").exists()
    assert (base / "catalog-info.yaml").exists()
    assert (base / ".github" / "copilot-instructions.md").exists()
    assert (base / "kb").exists()
    # repo-control files must land at the published REPO ROOT — GitHub ignores them under a subdir
    root = result.pr
    assert (root / ".github" / "CODEOWNERS").read_text() == "* REPLACE_ME__owning_team\n"
    assert (root / ".github" / "pull_request_template.md").exists()
    assert (root / ".sre" / "version").read_text().startswith("sre-kb==")
    assert (root / ".sre" / "schemas" / "_envelope.schema.json").exists()
    assert (root / ".sre" / "schemas" / "v1alpha1" / "Flow.schema.json").exists()
    wf = (root / ".github" / "workflows" / "validate-sre-kb.yml").read_text()
    assert "catalog/*/kb" in wf  # validate step targets the catalog layout, not a root-level kb/
    # the scheduled drift loop ships inert: a sentinel target the config guard turns into a no-op
    drift = (root / ".github" / "workflows" / "drift-sre-kb.yml").read_text()
    assert "REPLACE_ME__target_repo" in drift and "skip=true" in drift
    assert "sre-kb diff --from-kb" in drift and "--fail-on-drift" in drift
    # ...and they must NOT be nested under the service dir (the regression this guards against)
    assert not (base / ".github" / "CODEOWNERS").exists()
    assert not (base / ".github" / "workflows").exists()
    assert not (base / ".sre").exists()


def test_pr_title_is_single_line():
    from sre_kb.publish.pr_builder import _pr_title

    t = _pr_title("order-service\nInjected: malicious second line\n- rm -rf /")
    assert "\n" not in t
    assert t.startswith("SRE KB: order-service")


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


def test_publish_blocks_secret_before_redaction(tmp_path):
    from sre_kb.publish import assemble_pr
    from sre_kb.security import SecretLeakError
    from sre_kb.workspace import RunLayout

    layout = RunLayout(tmp_path, "secret")
    layout.ensure()
    docs = [{"kind": "Flow", "metadata": {"name": "f", "service": "svc"}, "spec": {}, "status": "verified"}]
    kb_file = layout.kb / "verified" / "Flow" / "f.yaml"
    kb_file.parent.mkdir(parents=True)
    kb_file.write_text("token: ghp_" + "a" * 36 + "\n", encoding="utf-8")
    proj = layout.root / "projections"
    (proj / ".github").mkdir(parents=True)
    (proj / ".github" / "copilot-instructions.md").write_text("ok\n", encoding="utf-8")
    (proj / "runbooks").mkdir()
    (proj / "catalog-info.yaml").write_text("apiVersion: backstage.io/v1alpha1\n", encoding="utf-8")

    with pytest.raises(SecretLeakError):
        assemble_pr(layout, docs, None, dry_run=True)

    assert "ghp_" in (layout.root / "pr" / "catalog" / "svc" / "kb" / "verified" / "Flow" / "f.yaml").read_text(
        encoding="utf-8"
    )


def test_publish_restages_cleanly_each_run(tmp_path):
    """Re-publish rebuilds the staging tree from scratch: a stale file from a prior run is gone.
    Operator edits are preserved in the published *target* repo by the forge's manifest merge (see
    test_forge_publish_preserves_operator_edit_and_prunes_orphan), not in this local staging dir."""
    first = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="restage", to_stage="publish")
    stray = first.pr / "catalog" / "order-service" / "STALE.txt"
    stray.write_text("left over from a prior run\n", encoding="utf-8")

    second = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="restage", to_stage="publish")

    assert not stray.exists()  # clean re-stage removed the stale file
    assert (second.pr / "catalog" / "order-service" / "REVIEW.md").exists()  # tree rebuilt


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


def test_generated_workflow_engine_install_is_configurable(tmp_path):
    """The engine is not on public PyPI: publish.engine_index_url / engine_spec decide where the
    generated CI installs the pinned engine from — without them it would fail on every run of the
    published repo (the distribution story made explicit)."""
    from sre_kb.publish.pr_builder import _stage_repo_root_hardening

    _stage_repo_root_hardening(tmp_path, {
        "engine_index_url": "https://pypi.internal.example/simple",
        "engine_spec": "sre-kb==0.0.1",
    })
    wf = (tmp_path / ".github" / "workflows" / "validate-sre-kb.yml").read_text()
    assert 'pip install --index-url https://pypi.internal.example/simple "$(cat .sre/version)"' in wf
    assert (tmp_path / ".sre" / "version").read_text() == "sre-kb==0.0.1\n"
    # the unconfigured default still pins this engine's own version
    _stage_repo_root_hardening(tmp_path, {})
    from sre_kb import __version__
    assert (tmp_path / ".sre" / "version").read_text() == f"sre-kb=={__version__}\n"


def test_generated_editor_settings_map_every_kind_to_its_vendored_schema(tmp_path):
    """Review-time validation for free: the published repo carries a yaml-language-server mapping
    from each kind's KB glob to the VENDORED schema — pinned to the version the artifacts were
    written against, not whatever the engine ships today."""
    import json as _json

    from sre_kb.publish.pr_builder import _stage_repo_root_hardening
    from sre_kb.registry import kinds

    _stage_repo_root_hardening(tmp_path, {})
    settings = _json.loads((tmp_path / ".vscode" / "settings.json").read_text())
    mapping = settings["yaml.schemas"]
    assert mapping[".sre/schemas/v1alpha1/Flow.schema.json"] == "catalog/*/kb/**/Flow/*.yaml"
    assert len(mapping) == len(kinds())  # every registered kind is covered
    for schema_path in mapping:          # every mapped schema is actually vendored beside it
        assert (tmp_path / schema_path).is_file(), schema_path
