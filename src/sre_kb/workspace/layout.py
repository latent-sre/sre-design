"""Ephemeral run-dir layout under .work/<run-id>/ — stages hand off via disk."""

from __future__ import annotations

import shutil
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

    def reset_kb(self) -> None:
        """Clear prior KB output (verified/needs-review + rejected) so a re-run under the same
        run-id can't leak stale artifacts into the result — e.g. `diff` reuses fixed run-ids, and a
        re-`run` with an explicit `--run` writes by name only, leaving orphaned/duplicated docs.
        Facts and candidates are intentionally left in place."""
        for d in (self.kb, self.reports / "rejected"):
            if d.exists():
                shutil.rmtree(d)
        for d in (self.kb / "verified", self.kb / "needs-review"):
            d.mkdir(parents=True, exist_ok=True)
