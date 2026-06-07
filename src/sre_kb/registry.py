"""Typed access to the kind registry (`schemas/registry.yaml`) — the one declarative table mapping a
kind to its schema, collectors, prompt, phase, and per-kind projection `renderer`.

Render routing reads this table instead of hard-coding ``if kind == ...``: adding a kind is one
registry row, plus (if it projects) one renderer entry. `tests/test_registry_governance.py` keeps the
table and the render code in lock-step, so a new kind can't silently skip a schema or a renderer
(HYBRID-PLAN §9.6 / DEEP-COMPARISON R5).
"""

from __future__ import annotations

from functools import cache

import yaml

from sre_kb.config import registry_path


@cache
def _registry() -> dict:
    with registry_path().open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def kinds() -> list[str]:
    """All registered kind names."""
    return list(_registry().get("kinds") or {})


def kind_meta(kind: str) -> dict:
    """The registry row for `kind` (schema/collectors/prompt/phase/renderer), or {} if unknown."""
    return (_registry().get("kinds") or {}).get(kind) or {}


def schema_for(kind: str) -> str | None:
    """The declared schema path for `kind`."""
    return kind_meta(kind).get("schema")


def renderer_for(kind: str) -> str | None:
    """The per-kind projection renderer (e.g. 'diagram', 'runbook'), or None for a KB-only kind that
    has no dedicated projection — the routing knob `render_projections` dispatches on."""
    return kind_meta(kind).get("renderer")
