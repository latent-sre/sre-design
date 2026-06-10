"""Structural validation (layer a): validate artifacts against JSON Schema.

Every artifact is validated against the shared envelope schema, and — when a per-kind
schema exists in schemas/v1alpha1/<Kind>.schema.json — against that too. Per-kind
schemas arrive incrementally (P1+); until a kind has one, the envelope still guarantees
the artifact is well-formed and carries provenance/status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache, lru_cache
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
    warnings: list[str] = field(default_factory=list)  # deprecations: surfaced, never failing


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


# Bounded, unlike the no-arg validators above: these are keyed on an arbitrary schema_root Path
# (the --schema-dir override / test path), so an unbounded @cache would grow without limit and pin a
# stale compiled validator if the schema on disk changes. A small LRU is plenty — few roots per run.
@lru_cache(maxsize=32)
def _envelope_validator_from(schema_root: Path) -> Draft202012Validator:
    return _validator_from_path(schema_root / "_envelope.schema.json")


@lru_cache(maxsize=32)
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


def _spec_properties(kind: str, schema_root: Path | None) -> dict:
    """The kind schema's spec property table (where deprecation/alias annotations live)."""
    kv = _kind_validator_from(schema_root, kind) if schema_root else _kind_validator(kind)
    if kv is None:
        return {}
    spec_schema = (kv.schema.get("properties") or {}).get("spec") or {}
    return spec_schema.get("properties") or {}


def canonicalize_doc(doc: dict, schema_root: Path | None = None) -> tuple[dict, list[str]]:
    """Schema evolution (§1.6): the soft-deprecation window ahead of any apiVersion bump.

    A renamed spec field keeps its old property in the schema, marked
    ``"deprecated": true, "x-renamed-to": "<newName>"`` alongside the new one. This function
    moves the old name's value to the new name (the new name wins when both are present) and
    collects a warning per deprecated field used — so old documents stay valid for one
    apiVersion while every reader sees only the canonical shape. Returns
    ``(canonical doc, warnings)``; the input is never mutated."""
    if not isinstance(doc, dict) or not isinstance(doc.get("spec"), dict) \
            or not isinstance(doc.get("kind"), str):
        return doc, []
    warnings: list[str] = []
    spec = dict(doc["spec"])
    changed = False
    for name, prop in _spec_properties(doc["kind"], schema_root).items():
        if not isinstance(prop, dict) or name not in spec:
            continue
        renamed_to = prop.get("x-renamed-to")
        if renamed_to:
            value = spec.pop(name)
            changed = True
            if renamed_to in spec:
                warnings.append(f"spec.{name} is deprecated and spec.{renamed_to} is also set "
                                "— the new name wins; the old value was ignored")
            else:
                spec[renamed_to] = value
                warnings.append(f"spec.{name} is deprecated — accepted as spec.{renamed_to} "
                                "(renamed; the old name is removed in the next apiVersion)")
        elif prop.get("deprecated"):
            warnings.append(f"spec.{name} is deprecated — it will be removed in the next "
                            "apiVersion")
    if not changed:
        return doc, warnings
    canonical = dict(doc)
    canonical["spec"] = spec
    return canonical, warnings


def validate_doc(doc: dict, schema_root: Path | None = None) -> list[str]:
    """Validate a single parsed artifact. Returns a list of error strings ([] = valid).
    Aliased (renamed) fields are canonicalized first, so a document written against the old
    name validates throughout its deprecation window."""
    canonical, _ = canonicalize_doc(doc, schema_root) if isinstance(doc, dict) else (doc, [])
    envelope = _envelope_validator_from(schema_root) if schema_root else _envelope_validator()
    errors = _format_errors(envelope, canonical)
    kind = canonical.get("kind") if isinstance(canonical, dict) else None
    if isinstance(kind, str):
        kv = _kind_validator_from(schema_root, kind) if schema_root else _kind_validator(kind)
        if kv is not None:
            errors += _format_errors(kv, canonical)
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
        _, warnings = canonicalize_doc(doc, schema_root=schema_root)
        results.append(DocResult(str(path), doc.get("kind"), not errors, errors, warnings))
    return results
