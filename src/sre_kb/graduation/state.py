"""Graduation loop (HYBRID-PLAN §7.9 / §9.3 #3): turn a recurring, human-confirmed gap category into a
deterministic engine signature so the gap-finder's recall ratchets upward over time.

A reviewer records a verdict with `sre-kb confirm-gap` each time they accept (or dismiss) a
needs-review gap; the tally lives in the target repo's `.sre/graduation-tracker.yaml`. Once a category
reaches the threshold with zero false positives it becomes a *promotion candidate*, and the engine
drafts the deterministic signature for a human to review and merge — assisted, never auto-applied. The
LLM scouts, a human approves, and the engine judges deterministically thereafter.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

TRACKER_REL = ".sre/graduation-tracker.yaml"
DEFAULT_THRESHOLD = 5
_MAX_ANCHORS = 5  # sample anchors kept per category, as evidence to seed the signature draft


@dataclass
class ConfirmedCategory:
    """Per-category graduation state: how many times a human confirmed it, how many were false
    positives, and a few sample anchors to seed the signature draft."""

    category: str
    confirmed: int = 0
    false_positives: int = 0
    last_run: str | None = None
    anchors: list[str] = field(default_factory=list)
    promoted: bool = False

    def is_candidate(self, threshold: int) -> bool:
        """Ready to graduate: enough confirmations, no false positives, not already promoted."""
        return not self.promoted and self.confirmed >= threshold and self.false_positives == 0


@dataclass
class GraduationTracker:
    """The tracked categories, persisted to `<root>/.sre/graduation-tracker.yaml` in the target repo."""

    categories: dict[str, ConfirmedCategory] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> GraduationTracker:
        """Read the tracker from `root/.sre/graduation-tracker.yaml`. A missing or corrupt file is an
        empty tracker, so a first confirmation just establishes one (no crash on hand-edits)."""
        path = root / TRACKER_REL
        if not path.is_file():
            return cls()
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return cls()
        cats: dict[str, ConfirmedCategory] = {}
        for name, raw in (doc.get("categories") or {}).items():
            raw = raw or {}
            cats[str(name)] = ConfirmedCategory(
                category=str(name),
                confirmed=int(raw.get("confirmed", 0)),
                false_positives=int(raw.get("false_positives", 0)),
                last_run=raw.get("last_run"),
                anchors=[str(a) for a in (raw.get("anchors") or [])],
                promoted=bool(raw.get("promoted", False)),
            )
        return cls(categories=cats)

    def save(self, root: Path) -> None:
        path = root / TRACKER_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "apiVersion": "sre.kb/v1alpha1",
            "kind": "GraduationTracker",
            "categories": {
                name: {
                    "confirmed": c.confirmed,
                    "false_positives": c.false_positives,
                    "last_run": c.last_run,
                    "anchors": list(c.anchors),
                    "promoted": c.promoted,
                }
                for name, c in sorted(self.categories.items())
            },
        }
        # Atomic write (temp + os.replace): a crash mid-write must not truncate the tracker —
        # load() treats a corrupt file as empty, which would silently discard the whole accumulating
        # tally (#M7). Concurrent confirm-gap runs are still last-writer-wins, but never corrupt.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".graduation-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(yaml.safe_dump(body, sort_keys=False))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _get(self, category: str) -> ConfirmedCategory:
        return self.categories.setdefault(category, ConfirmedCategory(category=category))

    def confirm(self, category: str, *, run: str | None = None, anchor: str | None = None) -> ConfirmedCategory:
        """Record one human confirmation of `category`."""
        cat = self._get(category)
        cat.confirmed += 1
        if run:
            cat.last_run = run
        if anchor and anchor not in cat.anchors:
            cat.anchors = (cat.anchors + [anchor])[-_MAX_ANCHORS:]
        return cat

    def refute(self, category: str) -> ConfirmedCategory:
        """Record one dismissed/false gap for `category` — any false positive blocks graduation."""
        cat = self._get(category)
        cat.false_positives += 1
        return cat

    def candidates(self, threshold: int = DEFAULT_THRESHOLD) -> list[ConfirmedCategory]:
        """Categories ready to graduate, in stable (name) order."""
        return [c for _, c in sorted(self.categories.items()) if c.is_candidate(threshold)]


def draft_signature(cat: ConfirmedCategory, concerns: tuple[str, ...]) -> str:
    """The assisted auto-draft: a human-reviewable sketch of the deterministic rule a promotion-ready
    category should become. The engine never edits its own rules — this is a suggestion to merge."""
    lines = [f"  draft for '{cat.category}' — review and merge by hand, never auto-applied:"]
    if cat.category == "swallowed-failure":
        lines.append("    graduates via the AST swallow detector (Call.swallow), not a regex signature;")
        lines.append("    extend that detector to cover the confirmed sites below.")
    elif concerns:
        lines.append(f"    add a pattern to signatures.py concern(s): {', '.join(concerns)}")
        lines.append('    patterns=_p(r"<regex that fires on the confirmed anchors>"),')
    else:
        lines.append("    judgment-call category — no deterministic signature; it stays Tier-B needs-review.")
    for anchor in cat.anchors:
        lines.append(f"    # confirmed anchor: {anchor}")
    return "\n".join(lines)
