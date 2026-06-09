"""Idempotency-on-mutating-route gaps (HYBRID-PLAN S4 quick win) — Tier-A recall.

A mutating HTTP endpoint (POST/PUT/PATCH/DELETE) with no idempotency guard in scope is a
deterministic, byte-grounded gap: a client retry (or a duplicate submit) re-applies the write. The
pieces already exist — the HTTP verb on each `rest.endpoint` and the shared `idempotency` signature —
so "mutating route with no idempotency guard in scope" graduates to a deterministic Tier-A gap, the
HTTP dual of S3's `non-idempotent-consumer`.

Scoping is conservative on purpose: the guard is sought in the handler's enclosing type, falling back
to the whole file. A wider scope means the engine only asserts the absence when idempotency is *truly
absent nearby* — a false-positive Tier-A `verified` gap is worse than a missed one, and the S4 confirm
loop is exactly how a reviewer/skill disputes a real guard the engine couldn't see (a global filter).
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, FactSet, Symbol
from sre_kb.signatures import fires
from sre_kb.util import slug

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_LANG = {".java": "java", ".cs": "csharp", ".py": "python",
         ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".go": "go"}


def _scope_text(ctx: ScanContext, rel: str, line: int) -> str:
    """The idempotency-search scope for a handler at `line`: its enclosing type, or — when the handler
    is a free function or the file can't be parsed into a type — the whole file (the conservative
    fallback, so a guard anywhere nearby refutes the absence)."""
    lang = _LANG.get(Path(rel).suffix)
    if lang is not None:
        module = ctx.module(rel, lang)
        t = next((t for t in module.types if t.start <= line <= t.end), None)
        if t is not None:
            return "".join(ctx.read_lines(rel)[t.start - 1 : t.end])
    return ctx.read_text(rel)


def collect_gaps(ctx: ScanContext, fs: FactSet) -> list[Fact]:
    """Tier-A `missing-idempotency` gaps for mutating routes with no idempotency guard in scope."""
    gaps: list[Fact] = []
    for ep in fs.of("rest.endpoint"):
        if ep.attrs.get("method") not in _MUTATING:
            continue
        rel = ep.evidence.path
        if fires("idempotency", _scope_text(ctx, rel, ep.evidence.lines.start)):
            continue  # an idempotency guard is in scope — not a gap
        route = f"{ep.attrs.get('method')} {ep.attrs.get('path', '/')}"
        gaps.append(Fact(
            "resiliency.gap",
            {
                "category": "missing-idempotency",
                "target": slug(route),
                "severity": "medium",
                "rationale": (
                    f"mutating route '{route}' ({ep.attrs.get('handler')}) has no idempotency guard "
                    "in scope — a client retry or duplicate submit re-applies the write."
                ),
                "rederivation": "mutating-route",
                "checked": [rel],
            },
            ep.evidence,
            Symbol(ep.attrs.get("handler") or route, "method"),
        ))
    return gaps
