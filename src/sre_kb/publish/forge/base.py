"""The Forge protocol — the SCM-neutral seam every publisher targets."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Forge(Protocol):
    name: str

    def open_pr(self, tree: Path, *, sre_repo: str, branch: str, title: str, body: str) -> str:
        """Push `tree` to `sre_repo` on `branch` and open a PR. Returns a URL/ref."""
        ...
