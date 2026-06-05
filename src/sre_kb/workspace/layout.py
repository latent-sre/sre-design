"""Ephemeral run-dir layout under .work/<run-id>/ — stages hand off via disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunLayout:
    work_root: Path
    run_id: str

    @property
    def root(self) -> Path:
        return self.work_root / self.run_id

    @property
    def facts(self) -> Path:
        return self.root / "facts"

    @property
    def candidates(self) -> Path:
        return self.root / "candidates"

    @property
    def kb(self) -> Path:
        return self.root / "kb"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    def kb_dir(self, status: str) -> Path:
        return self.kb / ("verified" if status == "verified" else "needs-review")

    def ensure(self) -> None:
        for d in (self.facts, self.candidates, self.kb / "verified", self.kb / "needs-review", self.reports):
            d.mkdir(parents=True, exist_ok=True)
