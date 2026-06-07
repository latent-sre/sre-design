"""Structural validation (layer a): validate artifacts against JSON Schema.

Every artifact is validated against the shared envelope schema, and — when a per-kind
schema exists in schemas/v1alpha1/<Kind>.schema.json — against that too. Per-kind
schemas arrive incrementally (P1+); until a kind has one, the envelope still guarantees
the artifact is well-formed and carries provenance/status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from sre_kb.config import schemas_dir


class StructuralError(Exception):
    """Raised when an artifact fails structural (schema) validation."""


@dataclass
class DocResult:
    path: str
    kind: str | None
    ok: bool
    errors: list[str] = field(default_factory=list)


@cache
def _envelope_validator() -> Draft202012Validator:
    schema_path = schemas_dir() / "_envelope.schema.json"
    return _validator_from_path(schema_path)


@cache
def _kind_validator(kind: str) -> Draft202012Validator | None:
    schema_path = schemas_dir() / "v1alpha1" / f"{kind}.schema.json"
    if not schema_path.exists():
        return None
    return _validator_from_path(schema_path)


def _validator_from_path(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@cache
def _envelope_validator_from(schema_root: Path) -> Draft202012Validator:
    return _validator_from_path(schema_root / "_envelope.schema.json")


@cache
def _kind_validator_from(schema_root: Path, kind: str) -> Draft202012Validator | None:
    schema_path = schema_root / "v1alpha1" / f"{kind}.schema.json"
    if not schema_path.exists():
        return None
    return _validator_from_path(schema_path)


def _format_errors(validator: Draft202012Validator, doc: dict) -> list[str]:
    msgs: list[str] = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        msgs.append(f"{loc}: {err.message}")
    return msgs


def validate_doc(doc: dict, schema_root: Path | None = None) -> list[str]:
    """Validate a single parsed artifact. Returns a list of error strings ([] = valid)."""
    envelope = _envelope_validator_from(schema_root) if schema_root else _envelope_validator()
    errors = _format_errors(envelope, doc)
    kind = doc.get("kind") if isinstance(doc, dict) else None
    if isinstance(kind, str):
        kv = _kind_validator_from(schema_root, kind) if schema_root else _kind_validator(kind)
        if kv is not None:
            errors += _format_errors(kv, doc)
    return errors


def validate_kb_tree(root: Path, schema_root: Path | None = None) -> list[DocResult]:
    """Validate every *.yaml/*.yml artifact under `root`. Used by `sre-kb validate-kb`."""
    results: list[DocResult] = []
    for path in sorted(root.rglob("*.y*ml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            results.append(DocResult(str(path), None, False, [f"YAML parse error: {exc}"]))
            continue
        if not isinstance(doc, dict):
            results.append(DocResult(str(path), None, False, ["not a mapping/object"]))
            continue
        errors = validate_doc(doc, schema_root=schema_root)
        results.append(DocResult(str(path), doc.get("kind"), not errors, errors))
    return results
