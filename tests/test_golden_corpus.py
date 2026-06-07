"""§7.6 golden corpus: one schema-valid example per kind, validated independently of a scan run.
A schema change that breaks a kind's shape (or a kind left without an example) is caught in CI,
and the corpus documents a complete, valid instance of every kind — the full-coverage check that
makes the per-kind `additionalProperties: false` allow-lists meaningful.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.config import registry_path, schemas_dir
from sre_kb.validation import validate_doc

GOLDEN = Path(__file__).parent / "fixtures" / "golden"
_FILES = sorted(GOLDEN.glob("*.yaml"))


@pytest.mark.parametrize("path", _FILES, ids=lambda p: p.stem)
def test_golden_example_validates(path: Path) -> None:
    assert validate_doc(yaml.safe_load(path.read_text(encoding="utf-8"))) == []


def test_every_per_kind_schema_has_a_golden_example() -> None:
    schema_kinds = {p.name[: -len(".schema.json")] for p in (schemas_dir() / "v1alpha1").glob("*.schema.json")}
    golden_kinds = {p.stem for p in _FILES}
    assert schema_kinds and schema_kinds <= golden_kinds, \
        f"per-kind schemas without a golden example: {sorted(schema_kinds - golden_kinds)}"


def test_registry_schema_paths_exist_and_have_golden_examples() -> None:
    registry = yaml.safe_load(registry_path().read_text(encoding="utf-8")) or {}
    kinds = registry.get("kinds") or {}
    missing_schema: list[str] = []
    missing_golden: list[str] = []
    golden_kinds = {p.stem for p in _FILES}
    for kind, entry in kinds.items():
        schema = (entry or {}).get("schema")
        if not schema:
            continue
        if not (registry_path().parents[1] / schema).exists():
            missing_schema.append(kind)
        if kind not in golden_kinds:
            missing_golden.append(kind)
    assert not missing_schema, f"registry kinds with missing schema paths: {missing_schema}"
    assert not missing_golden, f"registry kinds without golden examples: {missing_golden}"
