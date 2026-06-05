"""Provenance validation (layer b): recompute excerptHash for every evidence item and
confirm the cited bytes exist at the scanned path. This is the anti-hallucination gate."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import hash_excerpt


def verify_evidence(doc: dict, target_root: Path) -> list[str]:
    errors: list[str] = []
    for i, ev in enumerate(doc.get("evidence") or []):
        path = ev.get("path")
        lines = ev.get("lines") or {}
        start, end = lines.get("start"), lines.get("end")
        want = ev.get("excerptHash")
        fpath = target_root / path if path else None
        if not fpath or not fpath.exists():
            errors.append(f"evidence[{i}]: path not found: {path}")
            continue
        content = fpath.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        if not (isinstance(start, int) and isinstance(end, int)) or start < 1 or end > len(content):
            errors.append(f"evidence[{i}]: line range {start}-{end} out of bounds for {path}")
            continue
        got = hash_excerpt(content, start, end)
        if got != want:
            errors.append(f"evidence[{i}]: excerptHash mismatch at {path}:{start}-{end}")
    return errors
