"""Scan context + provenance hashing shared by all collectors.

`hash_excerpt` is the single source of truth for `excerptHash`; the provenance validator
recomputes it the same way, so a citation that doesn't match the bytes can't pass.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sre_kb.models.envelope import Evidence, Lines
from sre_kb.parsing import parse

if TYPE_CHECKING:
    from sre_kb.models.facts import Fact, FactSet
    from sre_kb.parsing import Module

LOCAL_COMMIT = "0" * 40  # sentinel commit for local working-tree scans
_SKIP_DIRS = {".git", ".venv", "venv", "target", "build", "node_modules", "__pycache__"}
_MAX_FILE_BYTES = 2_000_000  # skip pathologically large files (DoS / decompression-bomb guard)


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
    _modules: dict[tuple[str, str], Module] = field(default_factory=dict)

    def read_lines(self, rel: str) -> list[str]:
        if rel not in self._lines:
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            self._lines[rel] = text.splitlines(keepends=True)
        return self._lines[rel]

    def read_text(self, rel: str) -> str:
        return "".join(self.read_lines(rel))

    def module(self, rel: str, language: str) -> Module:
        """Parsed AST for `rel`, memoized per (path, language). Parsing is pure on the file text, so
        the cache lets every collector share one parse instead of re-parsing the same file (the Java
        collectors alone parsed each *.java up to ~5x per scan)."""
        key = (rel, language)
        if key not in self._modules:
            self._modules[key] = parse(language, self.read_text(rel))
        return self._modules[key]

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
                if p.stat().st_size > _MAX_FILE_BYTES:
                    continue  # resource budget (safe-by-default)
                out.append(p)
        return out

    def evidence(
        self, rel: str, start: int, end: int, detector: str, *, source_tier: str = "ast"
    ) -> Evidence:
        end = max(end, start)
        return Evidence(
            repo=self.repo,
            commit=self.commit,
            path=rel,
            lines=Lines(start=start, end=end),
            excerptHash=hash_excerpt(self.read_lines(rel), start, end),
            detector=detector,
            source_tier=source_tier,
        )


@runtime_checkable
class CollectorProtocol(Protocol):
    """The contract every collector satisfies — Tier-A (AST) and Tier-B (LLM) alike.

    File-collectors take only the ``ScanContext``; derivers also read the in-progress
    ``FactSet``. The ``fs`` parameter is optional so both call shapes — ``collect(ctx)``
    and ``collect(ctx, fs)`` — satisfy this single protocol.
    """

    def __call__(self, ctx: ScanContext, fs: FactSet | None = None) -> list[Fact]: ...
