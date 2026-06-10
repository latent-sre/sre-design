"""Schema evolution (§1.6): the soft-deprecation window — a renamed spec field stays valid
under its old name for one apiVersion (canonicalized + warned), and `deprecated: true`
fields warn without failing."""

from __future__ import annotations

import json
import shutil

import pytest

from sre_kb.config import schemas_dir
from sre_kb.validation.structural import canonicalize_doc, validate_doc, validate_kb_tree

_WIDGET_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Widget",
    "type": "object",
    "required": ["kind", "spec"],
    "properties": {
        "kind": {"const": "Widget"},
        "spec": {
            "type": "object",
            "additionalProperties": False,
            "required": ["maxLatencyMs"],
            "properties": {
                # the rename: timeoutMs -> maxLatencyMs, old name in its deprecation window
                "timeoutMs": {"type": "integer", "deprecated": True,
                              "x-renamed-to": "maxLatencyMs"},
                "maxLatencyMs": {"type": "integer"},
                # plain deprecation, no rename: still declared, warns on use
                "legacyFlag": {"type": "boolean", "deprecated": True},
            },
        },
    },
}


@pytest.fixture()
def schema_root(tmp_path):
    root = tmp_path / "schemas"
    (root / "v1alpha1").mkdir(parents=True)
    shutil.copy(schemas_dir() / "_envelope.schema.json", root / "_envelope.schema.json")
    (root / "v1alpha1" / "Widget.schema.json").write_text(json.dumps(_WIDGET_SCHEMA),
                                                          encoding="utf-8")
    return root


def _doc(spec: dict) -> dict:
    return {"apiVersion": "sre.kb/v1alpha1", "kind": "Widget",
            "metadata": {"name": "w"}, "spec": spec,
            "evidence": [{"repo": "r", "commit": "5f3e9c1a7b", "path": "p",  # pragma: allowlist secret
                          "lines": {"start": 1, "end": 1},
                          "excerptHash": "sha256:" + "0" * 64, "detector": "d"}],
            "status": "verified", "confidence": 0.9}


def test_old_field_name_validates_through_its_deprecation_window(schema_root):
    doc = _doc({"timeoutMs": 250})  # written against the OLD name; new name is required
    assert validate_doc(doc, schema_root=schema_root) == []
    canonical, warnings = canonicalize_doc(doc, schema_root=schema_root)
    assert canonical["spec"] == {"maxLatencyMs": 250}
    assert doc["spec"] == {"timeoutMs": 250}  # the input is never mutated
    assert any("accepted as spec.maxLatencyMs" in w for w in warnings)


def test_new_name_wins_when_both_are_present(schema_root):
    canonical, warnings = canonicalize_doc(_doc({"timeoutMs": 1, "maxLatencyMs": 2}),
                                           schema_root=schema_root)
    assert canonical["spec"] == {"maxLatencyMs": 2}
    assert any("the new name wins" in w for w in warnings)


def test_plain_deprecated_field_warns_without_failing(schema_root):
    doc = _doc({"maxLatencyMs": 5, "legacyFlag": True})
    assert validate_doc(doc, schema_root=schema_root) == []
    _, warnings = canonicalize_doc(doc, schema_root=schema_root)
    assert warnings == ["spec.legacyFlag is deprecated — it will be removed in the next "
                        "apiVersion"]


def test_kb_tree_results_carry_deprecation_warnings(schema_root, tmp_path):
    import yaml

    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "w.yaml").write_text(yaml.safe_dump(_doc({"timeoutMs": 250})), encoding="utf-8")
    results = validate_kb_tree(kb, schema_root=schema_root)
    assert len(results) == 1 and results[0].ok
    assert any("deprecated" in w for w in results[0].warnings)


def test_unknown_fields_still_fail_aliasing_never_papers_over(schema_root):
    errors = validate_doc(_doc({"maxLatencyMs": 5, "typoField": 1}), schema_root=schema_root)
    assert any("typoField" in e for e in errors)  # additionalProperties still enforced


def test_load_kb_canonicalizes_renamed_fields_for_every_reader(schema_root, tmp_path, monkeypatch):
    """§1.6's promise holds downstream: a doc written against the OLD field name reads
    canonically from load_kb, so renderers/findings see the new name — not just validation."""
    import yaml

    from sre_kb.render import load_kb
    from sre_kb.validation import structural

    monkeypatch.setattr(
        structural, "_spec_properties",
        lambda kind, root=None: {"timeoutMs": {"deprecated": True,
                                               "x-renamed-to": "maxLatencyMs"}})
    kb = tmp_path / "run" / "kb" / "verified" / "Widget"
    kb.mkdir(parents=True)
    (kb / "w.yaml").write_text(yaml.safe_dump(_doc({"timeoutMs": 250})), encoding="utf-8")
    [doc] = load_kb(tmp_path / "run")
    assert doc["spec"] == {"maxLatencyMs": 250}
