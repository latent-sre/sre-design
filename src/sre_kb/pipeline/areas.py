"""Tier-B coverage discovery (the production-run finding, 2026-06-11) — the engine half of
discover-areas.

The gap-finder widens recall *within* the gap taxonomy; this loop widens the engine's
*coverage*: which parts of the repo the engine never looked at, and what it should learn to
collect there. The skill/provider proposes AREAS over the deterministic coverage ledger
(`reporting/coverage.py`); the engine re-grounds each on the usual non-circular contract:

  locate — the cited evidence must exist verbatim in the repo (anywhere; areas live exactly
           where the curated glob universes don't reach), else dropped;
  refute — an area whose cited files already produced facts is something the engine ALREADY
           covers (fact-set refutation, the R6 pattern), else routed;
  route  — survivors become engine recommendations (`reports/engine-recommendations.json` +
           a human-readable markdown), advisory and `source: llm`, never artifacts.

The flywheel: a reviewer confirms a recurring area with
`sre-kb confirm-gap area-<name> --novel`; the existing graduation tracker accrues it, and
the graduation sketch for an `area-*` category drafts a NEW COLLECTOR (globs, fact types,
kind, registry row) instead of a regex — recommendations compound into engine growth, runs
ratchet coverage upward.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.llm.gap_finder import is_valid_novel_category, locate

# Conventional location of the skill's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/area-proposals.json"
RECOMMENDATIONS_NAME = "engine-recommendations"

# Area anchors live precisely where the curated glob universes don't reach.
_ANY_FILE = ("*",)


@dataclass(frozen=True)
class AreaProposal:
    name: str
    evidence: str
    files: tuple[str, ...] = ()
    missing: str | None = None
    proposal: str | None = None


@dataclass
class AreaOutcome:
    proposal: AreaProposal
    result: str  # routed | refuted | unlocatable | invalid-name
    path: str | None = None
    line: int | None = None
    note: str = ""


@dataclass
class AreaResult:
    outcomes: list[AreaOutcome] = field(default_factory=list)

    def kept(self) -> list[AreaOutcome]:
        return [o for o in self.outcomes if o.result == "routed"]


def load_proposals(path: Path) -> list[AreaProposal]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for a in (doc.get("areas") or []) if isinstance(doc, dict) else []:
        if isinstance(a, dict) and a.get("name") and a.get("evidence"):
            out.append(AreaProposal(
                str(a["name"]), str(a["evidence"]),
                tuple(str(f) for f in (a.get("files") or []) if isinstance(f, str)),
                str(a["missing"]) if a.get("missing") else None,
                str(a["proposal"]) if a.get("proposal") else None))
    return out


def covered_paths(facts_jsonl: Path) -> set[str]:
    """Every repo path at least one fact cites — what the engine provably looked at."""
    covered: set[str] = set()
    try:
        lines = facts_jsonl.read_text(encoding="utf-8").splitlines()
    except OSError:
        return covered
    for line in lines:
        try:
            rel = json.loads(line).get("evidence", {}).get("path")
        except ValueError:
            continue
        if rel:
            covered.add(rel)
    return covered


def apply_areas(ctx: ScanContext, proposals: list[AreaProposal],
                covered: set[str]) -> AreaResult:
    result = AreaResult()
    for p in proposals:
        if not is_valid_novel_category(p.name):
            result.outcomes.append(AreaOutcome(p, "invalid-name",
                                               note="area name must be kebab-case"))
            continue
        loc = locate(ctx, p.evidence, _ANY_FILE)
        if loc is None:
            result.outcomes.append(AreaOutcome(
                p, "unlocatable", note="evidence not found verbatim in the target"))
            continue
        rel, start, _ = loc
        cited = set(p.files) | {rel}
        already = sorted(cited & covered)
        if already:
            result.outcomes.append(AreaOutcome(
                p, "refuted", rel, start,
                f"the engine already collects from {', '.join(already)} — not a blind spot"))
            continue
        result.outcomes.append(AreaOutcome(p, "routed", rel, start,
                                           "grounded in an uncovered file"))
    return result


def _render_md(kept: list[AreaOutcome]) -> str:
    out = ["# Engine recommendations — coverage areas the scan does not reach", "",
           "**Advisory, LLM-proposed, engine-grounded.** Each area below cites verbatim bytes "
           "in files no fact covers. Confirm a recurring one with "
           "`sre-kb confirm-gap area-<name> --novel --target <repo>`; at the graduation "
           "threshold the engine drafts the collector sketch.", ""]
    for o in kept:
        out += [f"## area-{o.proposal.name}",
                f"- **anchor:** `{o.path}:{o.line}`",
                f"- **files:** {', '.join(o.proposal.files) or o.path}",
                f"- **missing:** {o.proposal.missing or '—'}",
                f"- **proposed collection:** {o.proposal.proposal or '—'}", ""]
    return "\n".join(out)


def run_discover_areas(target: str, facts_jsonl: Path, reports_dir: Path) -> AreaResult:
    """Re-ground the target's area proposals against the run's fact ledger and write the
    surviving recommendations (JSON + markdown) into the run's reports."""
    root = Path(target).resolve()
    ctx = ScanContext(root=root, repo=root.as_uri(), commit=LOCAL_COMMIT)
    proposals = load_proposals(root / PROPOSALS_REL)
    result = apply_areas(ctx, proposals, covered_paths(facts_jsonl))
    kept = result.kept()
    if kept:
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / f"{RECOMMENDATIONS_NAME}.json").write_text(json.dumps({
            "recommendations": [{
                "area": f"area-{o.proposal.name}",
                "anchor": f"{o.path}:{o.line}",
                "files": list(o.proposal.files),
                "missing": o.proposal.missing,
                "proposal": o.proposal.proposal,
                "source": "llm",
                "advisory": True,
            } for o in kept]}, indent=2), encoding="utf-8")
        (reports_dir / f"{RECOMMENDATIONS_NAME}.md").write_text(_render_md(kept),
                                                                encoding="utf-8")
    return result
