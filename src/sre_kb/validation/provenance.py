"""Provenance validation (layer b): recompute excerptHash for every evidence item and
confirm the cited bytes exist at the scanned path. This is the anti-hallucination gate.

`verify_evidence` checks a single-repo artifact; `verify_evidence_roots` checks an
estate-level artifact whose evidence spans multiple repos (keyed by `evidence.repo`).
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import hash_excerpt


def _verify_one(ev: dict, root: Path, i: int) -> list[str]:
    path = ev.get("path")
    lines = ev.get("lines") or {}
    start, end = lines.get("start"), lines.get("end")
    want = ev.get("excerptHash")
    fpath = root / path if path else None
    if not fpath or not fpath.exists():
        return [f"evidence[{i}]: path not found: {path}"]
    content = fpath.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if not (isinstance(start, int) and isinstance(end, int)) or start < 1 or end > len(content):
        return [f"evidence[{i}]: line range {start}-{end} out of bounds for {path}"]
    if hash_excerpt(content, start, end) != want:
        return [f"evidence[{i}]: excerptHash mismatch at {path}:{start}-{end}"]
    return []


def verify_evidence(doc: dict, target_root: Path) -> list[str]:
    errors: list[str] = []
    for i, ev in enumerate(doc.get("evidence") or []):
        errors += _verify_one(ev, target_root, i)
    return errors


def verify_evidence_roots(doc: dict, roots: dict[str, Path]) -> list[str]:
    errors: list[str] = []
    for i, ev in enumerate(doc.get("evidence") or []):
        root = roots.get(ev.get("repo"))
        if root is None:
            errors.append(f"evidence[{i}]: unknown repo {ev.get('repo')}")
            continue
        errors += _verify_one(ev, root, i)
    return errors
