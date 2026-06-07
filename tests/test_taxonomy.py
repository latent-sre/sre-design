"""HYBRID-PLAN §9.7 N4 — central controlled vocabularies. schemas/taxonomy.yaml is the single source
of truth; these tests keep every schema enum and engine constant conformant so the vocabulary can't
drift, and verify severity reconciliation across schemes."""

from __future__ import annotations

import json

import sre_kb.taxonomy as tax
from sre_kb.config import schemas_dir
from sre_kb.taxonomy import reconcile_severity, severity_rank, severity_shapes, values, vocab


def _all_enum_sets(node) -> list[set[str]]:
    """Every `enum` array anywhere in a JSON Schema, as sets of its string members."""
    found: list[set[str]] = []
    if isinstance(node, dict):
        enum = node.get("enum")
        if isinstance(enum, list) and all(isinstance(v, str) for v in enum):
            found.append(set(enum))
        for value in node.values():
            found += _all_enum_sets(value)
    elif isinstance(node, list):
        for value in node:
            found += _all_enum_sets(value)
    return found


def _schema(rel: str) -> dict:
    return json.loads((schemas_dir() / rel).read_text(encoding="utf-8"))


def _schema_files() -> list[str]:
    return ["_envelope.schema.json"] + [
        f"v1alpha1/{p.name}" for p in sorted((schemas_dir() / "v1alpha1").glob("*.schema.json"))
    ]


# --- taxonomy coherence ---------------------------------------------------------------------------
def test_severity_scale_is_ordered_and_ranks():
    assert vocab("severity") == ["critical", "high", "medium", "low"]
    assert severity_rank("critical") < severity_rank("high") < severity_rank("medium") < severity_rank("low")
    assert severity_rank("unknown") == len(vocab("severity"))  # unscored sorts last, never outranks


def test_sanctioned_severity_shapes_use_only_canonical_values():
    allowed = values("severity") | {"unknown"}
    for shape in severity_shapes():
        assert shape <= allowed
    assert values("severity") in severity_shapes()  # the canonical scale itself is sanctioned


def test_severity_reconciliation_maps_every_scheme_onto_canonical():
    assert reconcile_severity("sev1") == "critical"
    assert reconcile_severity("P2") == "high"  # case-insensitive
    assert reconcile_severity("blocker") == "critical"
    assert reconcile_severity("3") == "medium"
    assert reconcile_severity("high") == "high"  # canonical passes through
    assert reconcile_severity("nonsense") is None
    assert set(tax._taxonomy()["severity_aliases"].values()) <= values("severity")


# --- engine constants conform ---------------------------------------------------------------------
def test_code_constants_match_taxonomy():
    from sre_kb.render.alerts import SEVERITY_RANK, TIER_SEVERITY_FLOOR

    assert SEVERITY_RANK == {s: i for i, s in enumerate(vocab("severity"))}
    assert set(TIER_SEVERITY_FLOOR) <= values("criticality_tier")  # keys are criticality tiers
    assert set(TIER_SEVERITY_FLOOR.values()) <= values("severity")  # floors are severities


# --- schemas conform (the drift-killer) -----------------------------------------------------------
def test_governed_vocabularies_have_their_canonical_home():
    env = _all_enum_sets(_schema("_envelope.schema.json"))
    assert values("status") in env
    assert values("ownership") in env
    assert values("source_tier") in env
    crit = _all_enum_sets(_schema("v1alpha1/Criticality.schema.json"))
    assert values("criticality_tier") in crit
    assert values("data_classification") in crit


def test_no_unsanctioned_severity_enum_drift():
    sev = values("severity")
    sanctioned = severity_shapes()
    for rel in _schema_files():
        for enum_set in _all_enum_sets(_schema(rel)):
            if enum_set & sev and enum_set <= (sev | {"unknown"}):  # a severity-family enum
                assert enum_set in sanctioned, f"{rel}: unsanctioned severity enum {sorted(enum_set)}"


def test_source_tier_enum_is_canonical_everywhere():
    tier = values("source_tier")
    for rel in _schema_files():
        for enum_set in _all_enum_sets(_schema(rel)):
            if enum_set & tier:  # any enum mentioning ast/llm must be exactly the source_tier set
                assert enum_set == tier, f"{rel}: source_tier-ish enum {sorted(enum_set)} != {sorted(tier)}"
