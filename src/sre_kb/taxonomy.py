"""Central controlled vocabularies (HYBRID-PLAN §9.7 N4): the single source of truth for the enums
that recur across the kind schemas and the engine — severity (+ cross-scheme reconciliation), status,
source_tier, ownership, criticality tiers, and data classification.

The schemas and engine code conform to `schemas/taxonomy.yaml`; `tests/test_taxonomy.py` enforces it,
so the vocabulary can't drift. A value is added, renamed, or reordered there, once.
"""

from __future__ import annotations

from functools import cache

import yaml

from sre_kb.config import schemas_dir


@cache
def _taxonomy() -> dict:
    with (schemas_dir() / "taxonomy.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def vocab(name: str) -> list[str]:
    """The canonical, ordered values of a controlled vocabulary (e.g. ``vocab("severity")``)."""
    try:
        return list(_taxonomy()["vocabularies"][name])
    except KeyError as exc:
        raise KeyError(f"unknown vocabulary: {name!r}") from exc


def values(name: str) -> set[str]:
    """The vocabulary as an (order-agnostic) set."""
    return set(vocab(name))


def severity_rank(severity: str) -> int:
    """Rank a severity by the canonical scale (0 = most severe). An unknown/unscored value sorts last,
    so it never outranks a real severity."""
    order = vocab("severity")
    return order.index(severity) if severity in order else len(order)


def reconcile_severity(token: str) -> str | None:
    """Map a token from any supported severity scheme (canonical, sevN, pN, blocker/major/minor/...,
    numeric) onto the canonical scale; ``None`` if unrecognized. Case-insensitive."""
    t = str(token).strip().lower()
    if t in values("severity"):
        return t
    return _taxonomy().get("severity_aliases", {}).get(t)


def severity_shapes() -> list[set[str]]:
    """The sanctioned severity-family enum shapes (sets), for the schema drift check."""
    return [set(shape) for shape in _taxonomy().get("severity_shapes", [])]
