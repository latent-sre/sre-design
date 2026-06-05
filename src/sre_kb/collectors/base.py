"""Scan context + provenance hashing shared by all collectors.

`hash_excerpt` is the single source of truth for `excerptHash`; the provenance validator
recomputes it the same way, so a citation that doesn't match the bytes can't pass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.models.envelope import Evidence, Lines

LOCAL_COMMIT = "0" * 40  # sentinel commit for local working-tree scans
_SKIP_DIRS = {".git", ".venv", "venv", "target", "build", "node_modules", "__pycache__"}


def hash_excerpt(lines: list[str], start: int, end: int) -> str:
    """SHA-256 of the exact cited byte range (1-based, inclusive). Keystone of provenance."""
    chunk = "".join(lines[start - 1 : end])
    return "sha256:" + hashlib.sha256(chunk.encode("utf-8")).hexdigest()


@dataclass
class ScanContext:
    root: Path
    repo: str
    commit: str = LOCAL_COMMIT
    _lines: dict[str, list[str]] = field(default_factory=dict)

    def read_lines(self, rel: str) -> list[str]:
        if rel not in self._lines:
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            self._lines[rel] = text.splitlines(keepends=True)
        return self._lines[rel]

    def read_text(self, rel: str) -> str:
        return "".join(self.read_lines(rel))

    def rel(self, path: Path) -> str:
        return str(path.relative_to(self.root)).replace("\\", "/")

    def files(self, *patterns: str) -> list[Path]:
        out: list[Path] = []
        for pattern in patterns:
            for p in sorted(self.root.rglob(pattern)):
                if p.is_symlink() or not p.is_file():
                    continue  # no symlink-follow (safe-by-default)
                if any(part in _SKIP_DIRS for part in p.relative_to(self.root).parts):
                    continue
                out.append(p)
        return out

    def evidence(self, rel: str, start: int, end: int, detector: str) -> Evidence:
        end = max(end, start)
        return Evidence(
            repo=self.repo,
            commit=self.commit,
            path=rel,
            lines=Lines(start=start, end=end),
            excerptHash=hash_excerpt(self.read_lines(rel), start, end),
            detector=detector,
        )
