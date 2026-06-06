"""§7.6 golden corpus: one schema-valid example per kind, validated independently of a scan run.
A schema change that breaks a kind's shape (or a kind left without an example) is caught in CI,
and the corpus documents a complete, valid instance of every kind — the full-coverage check that
makes the per-kind `additionalProperties: false` allow-lists meaningful.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.config import schemas_dir
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
