"""Tier-B architecture mapping (SCOPE coverage #2 + #3) — the engine half of map-architecture.

The deterministic inventory scaffolder already derives the component/layer skeleton and the
mechanism patterns its signatures byte-prove (circuit-breaker, fallback, repository,
async-messaging). What the structure *embodies* — CQRS, saga, transactional outbox, hexagonal —
is semantic judgment, so the `map-architecture` skill proposes it and the engine re-grounds each
proposal on the same non-circular contract the gap-finder uses:

  locate  — find the proposed anchor verbatim in the source; an anchor not present is dropped.
  refute  — drop any pattern the deterministic scan already proves (it is a duplicate, with byte
            proof on the Tier-A side).
  route   — a survivor is a genuine semantic claim: stamped `source_tier=llm` and folded into a
            `needs-review` Architecture artifact, never auto-verified.

The engine never calls a model here — it ingests proposals the skill already wrote (manually in
the IDE, or via `worklist-run`/`autopilot` through the provider seam).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.llm.gap_finder import locate
from sre_kb.scoring.confidence import Signal, confidence
from sre_kb.synth.emit import emit
from sre_kb.synth.scaffold import scaffold
from sre_kb.tiers import LLM
from sre_kb.util import slug

# Conventional location of the skill's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/architecture-proposals.json"


@dataclass(frozen=True)
class ArchitectureProposal:
    """One design-pattern hypothesis. `anchor` is verbatim code, never a line number."""

    pattern: str
    anchor: str
    rationale: str | None = None


@dataclass
class ArchitectureOutcome:
    """Per-proposal audit trail — why a proposed pattern was kept or dropped."""

    proposal: ArchitectureProposal
    result: str  # routed | refuted | unlocatable
    path: str | None = None
    lines: tuple[int, int] | None = None
    note: str = ""


@dataclass
class ArchitectureResult:
    outcomes: list[ArchitectureOutcome] = field(default_factory=list)
    docs: list[dict] = field(default_factory=list)

    def kept(self) -> list[ArchitectureOutcome]:
        return [o for o in self.outcomes if o.result == "routed"]

    def dropped(self) -> list[ArchitectureOutcome]:
        return [o for o in self.outcomes if o.result != "routed"]


def load_proposals(path: Path) -> list[ArchitectureProposal]:
    """Parse a skill-produced proposals file (a bare list or {"proposals": [...]})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("proposals", []) if isinstance(data, dict) else data
    out: list[ArchitectureProposal] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        pattern = slug(str(it.get("pattern") or "").strip().lower())
        anchor = str(it.get("anchor") or it.get("excerpt") or "").strip()
        if not pattern or not anchor:
            continue  # a patternless/anchorless proposal can't be grounded
        out.append(ArchitectureProposal(
            pattern=pattern,
            anchor=anchor,
            rationale=(str(it["rationale"]) if it.get("rationale") else None),
        ))
    return out


def known_patterns(docs: list[dict]) -> set[str]:
    """The patterns the deterministic scan already proves — a proposal for one is a duplicate."""
    return {p for d in docs if d.get("kind") == "Architecture"
            for p in (d.get("spec", {}).get("patterns") or [])}


def reground(ctx: ScanContext, proposals: list[ArchitectureProposal], docs: list[dict],
             service: str) -> ArchitectureResult:
    """Locate -> refute-duplicates -> route every proposal. Survivors fold into one needs-review
    Architecture artifact (`<service>-proposed-patterns`), one evidence citation per pattern."""
    known = known_patterns(docs)
    res = ArchitectureResult()
    routed: list[tuple[str, object]] = []
    seen: set[str] = set()
    for p in proposals:
        if p.pattern in known:
            res.outcomes.append(ArchitectureOutcome(
                p, "refuted", note=f"'{p.pattern}' is already deterministically detected"))
            continue
        loc = locate(ctx, p.anchor)
        if loc is None:
            res.outcomes.append(ArchitectureOutcome(
                p, "unlocatable", note="anchor not found verbatim in the source"))
            continue
        rel, s, e = loc
        evidence = ctx.evidence(rel, s, e, "llm.map_architecture", source_tier=LLM)
        if p.pattern not in seen:  # two anchors for one pattern: keep the first citation
            routed.append((p.pattern, evidence))
            seen.add(p.pattern)
        res.outcomes.append(ArchitectureOutcome(
            p, "routed", rel, (s, e),
            note=f"grounded at {rel}:{s} — routed to review"))
    if routed:
        res.docs.append(emit(
            "Architecture", f"{service}-proposed-patterns",
            {"components": [], "patterns": [pat for pat, _ in routed]},
            [ev for _, ev in routed], "needs-review", confidence(Signal.INFERRED),
            service, provenance="llm-asserted"))
    return res


def run_map_architecture(
    target: str, *, proposals_path: str | Path | None = None, service: str | None = None
) -> ArchitectureResult:
    """Scan + scaffold `target`, then re-ground its architecture proposals. No file -> empty result."""
    root = Path(target).resolve()
    if not root.exists():
        raise FileNotFoundError(f"target not found: {root}")
    ctx = ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)
    path = Path(proposals_path) if proposals_path else (root / PROPOSALS_REL)
    if not path.exists():
        return ArchitectureResult()
    try:
        proposals = load_proposals(path)
    except (json.JSONDecodeError, OSError):
        return ArchitectureResult()  # a malformed proposals file self-gates to "no proposals"
    docs = scaffold(scan(ctx), ctx)
    return reground(ctx, proposals, docs, service or root.name)
