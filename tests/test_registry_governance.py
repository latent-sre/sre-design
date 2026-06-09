"""R5 (DEEP-COMPARISON / HYBRID-PLAN §9.6): the kind registry is the one declarative table, and render
routing reads it. These tests keep the table and the code in lock-step, so adding a kind can't
silently skip its schema or its projection renderer."""

from __future__ import annotations

from sre_kb.config import schemas_dir
from sre_kb.registry import kind_meta, kinds, renderer_for, schema_for
from sre_kb.render.project import _PROJECTION_RENDERERS


def test_every_kind_has_an_existing_schema():
    assert kinds()  # the registry is non-empty
    for k in kinds():
        assert schema_for(k), f"{k} declares no schema"
        assert (schemas_dir() / "v1alpha1" / f"{k}.schema.json").is_file(), f"{k} schema file is missing"


def test_no_schema_file_is_orphaned_from_the_registry():
    """The reverse lock-step: a per-kind schema file dropped into v1alpha1/ without a registry row
    would never be routed (no collector/prompt/renderer wiring) and would silently rot. Every schema
    file must correspond to a registered kind (the shared `_envelope` lives a directory up, not here)."""
    registered = set(kinds())
    on_disk = {p.name[: -len(".schema.json")]
               for p in (schemas_dir() / "v1alpha1").glob("*.schema.json")}
    orphans = on_disk - registered
    assert not orphans, f"schema files with no registry row: {sorted(orphans)}"


def test_registry_renderers_and_implementations_are_in_lockstep():
    declared = {renderer_for(k) for k in kinds()} - {None}
    # every renderer a kind declares is implemented ...
    for r in declared:
        assert r in _PROJECTION_RENDERERS, f"registry declares renderer '{r}' with no implementation"
    # ... and every implemented renderer is reachable from the registry (no orphan/hard-coded handler)
    assert set(_PROJECTION_RENDERERS) == declared


def test_known_kinds_declare_expected_renderers():
    assert renderer_for("Flow") == "diagram"
    assert renderer_for("Runbook") == "runbook"
    assert renderer_for("TechStack") is None  # a KB-only kind has no projection renderer


def test_kind_meta_unknown_is_empty():
    assert kind_meta("NotAKind") == {}
    assert renderer_for("NotAKind") is None
