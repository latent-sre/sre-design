"""Local forge: stages the tree on disk (backs --dry-run). Opens no PR."""

from __future__ import annotations

from pathlib import Path


class LocalForge:
    name = "local"

    def open_pr(self, tree: Path, *, sre_repo: str, branch: str, title: str, body: str) -> str:
        return f"dry-run: staged PR tree at {tree} (would target {sre_repo}@{branch})"
