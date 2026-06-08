"""Renderers tolerate partial/hand-authored specs instead of crashing on them."""

from __future__ import annotations

from sre_kb.render.catalog import catalog_info
from sre_kb.render.copilot import runbook_markdown


def test_runbook_renders_string_diagnosis_steps():
    """Diagnosis items may be plain strings (hand/LLM-authored), not just {"step": ...} dicts —
    the renderer must not AttributeError on `str.get`."""
    rb = runbook_markdown(
        {"metadata": {"name": "r"}, "spec": {"diagnosis": ["check the dashboard", {"step": "tail logs"}]}},
        None,
    )
    assert "1. check the dashboard" in rb     # string step rendered
    assert "1. tail logs" in rb               # dict step still works


def test_catalog_owner_is_passed_through_when_present():
    """owner used to be hardcoded "unknown", dropping a declared owner."""
    docs = [{"kind": "ServiceCatalogEntry", "spec": {"owner": "team-orders"}}]
    assert catalog_info("orders", docs)["spec"]["owner"] == "team-orders"
    # absent owner still defaults
    assert catalog_info("orders", [])["spec"]["owner"] == "unknown"
