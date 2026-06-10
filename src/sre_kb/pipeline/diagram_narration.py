"""Tier-B diagram narration (NEXT-INCREMENTS §3.2 / §2.6) — the engine half of
narrate-diagrams. Drawings are the one projection with no prose: the provider writes the
one-paragraph "what this shows / what to worry about" caption from the artifact JSON
(closed-world input), and the engine appends it to the rendered diagram markdown **clearly
labeled advisory** — pointer-generator rules, never a fact source.

Deterministic gate: a narration must name a diagram this run actually rendered (anything
else is dropped), and the text is sanitized to one plain paragraph (whitespace collapsed,
backticks stripped, hard length cap) so a hostile reply can't smuggle markdown/fence
structure into the projection.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.render.diagrams import DIAGRAM_FILE_STEM
from sre_kb.workspace import RunLayout

# Conventional location of the skill's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/diagram-narrations.json"

_MAX_CHARS = 600
_BANNER = "> **Narration (LLM, advisory)** — verify against the drawing: "

# Diagram-bearing kinds -> the markdown file their renderer writes. Derived from the
# renderer-owned stem map so the two sides cannot drift.
_DIAGRAM_FILE = {kind: stem + ".md" for kind, stem in DIAGRAM_FILE_STEM.items()}


@dataclass
class NarrationOutcome:
    diagram: str
    result: str  # applied | unknown-diagram | empty
    note: str = ""
    path: Path | None = None


@dataclass
class NarrationResult:
    outcomes: list[NarrationOutcome] = field(default_factory=list)

    def applied(self) -> list[NarrationOutcome]:
        return [o for o in self.outcomes if o.result == "applied"]


def diagram_docs(docs: list[dict]) -> list[dict]:
    """The run's diagram-bearing artifacts (the narration candidates)."""
    return [d for d in docs
            if d.get("kind") in _DIAGRAM_FILE and (d.get("metadata") or {}).get("name")]


def _sanitize(text: str) -> str:
    """One plain advisory paragraph: whitespace collapsed, backticks/fence syntax stripped,
    hard length cap. The reply is untrusted — it must not be able to open a markdown block."""
    flat = re.sub(r"\s+", " ", str(text)).replace("`", "").strip()
    return flat[:_MAX_CHARS]


def apply_narrations(layout: RunLayout, docs: list[dict], proposals_path: Path) -> NarrationResult:
    result = NarrationResult()
    try:
        doc = json.loads(proposals_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    by_name = {d["metadata"]["name"]: d for d in diagram_docs(docs)}
    diagrams_dir = layout.root / "projections" / "diagrams"
    for n in (doc.get("narrations") or []) if isinstance(doc, dict) else []:
        if not isinstance(n, dict):
            continue
        name = str(n.get("diagram") or "")
        target_doc = by_name.get(name)
        if target_doc is None:
            result.outcomes.append(NarrationOutcome(
                name or "?", "unknown-diagram", "no rendered diagram has this name"))
            continue
        text = _sanitize(n.get("text") or "")
        if not text:
            result.outcomes.append(NarrationOutcome(name, "empty", "no usable text"))
            continue
        md = diagrams_dir / _DIAGRAM_FILE[target_doc["kind"]].format(name)
        if not md.is_file():
            result.outcomes.append(NarrationOutcome(
                name, "unknown-diagram", f"projection not rendered: {md.name}"))
            continue
        md.write_text(md.read_text(encoding="utf-8").rstrip("\n")
                      + f"\n\n{_BANNER}{text}\n", encoding="utf-8")
        result.outcomes.append(NarrationOutcome(name, "applied", f"{len(text)} char(s)", md))
    return result
