"""Tier-B API-contract re-grounding (coverage #7 versioning) — the engine half of map-api-contracts.

The deterministic `common.openapi` collector already classifies every *structural* breaking change vs
the committed `.sre/api-baseline/` baseline (operation removed/added, newly-required parameter) and the
semver version-policy. This module ingests the Tier-B `map-api-contracts` skill's proposals — the
*semantic* breaks the shape diff can't see (units/default/enum meaning) — and re-grounds each on the
exact same non-circular contract the gap-finder uses:

  locate  — find the proposed anchor verbatim in the CURRENT spec; an anchor not present is dropped.
  refute  — drop any proposal whose operation the deterministic diff already flags as a structural
            change (it is not a semantic break — it is already covered, with byte proof).
  route   — a survivor is a genuine semantic break: it can't be deterministically confirmed, so it is
            stamped `source_tier=llm` and routed to review (`needs-review`), never auto-verified.

The engine never calls a model: it ingests proposals Copilot already wrote by running the skill.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.common import openapi
from sre_kb.models.envelope import Evidence
from sre_kb.tiers import LLM

# Conventional location of the skill's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/contract-proposals.json"


@dataclass(frozen=True)
class ContractProposal:
    """One semantic-break hypothesis. `anchor` is verbatim current-spec text, never a line number;
    `target` is the operation ("GET /api/v1/orders/{id}"); `was` is the prior meaning."""

    target: str
    anchor: str
    severity: str = "medium"
    was: str | None = None
    rationale: str | None = None
    category: str = "semantic-break"


@dataclass
class ContractOutcome:
    """Per-proposal audit trail — the go/no-go evidence for whether the proposal grounds."""

    proposal: ContractProposal
    result: str  # routed | refuted | unlocatable
    path: str | None = None
    lines: tuple[int, int] | None = None
    evidence: Evidence | None = None
    note: str = ""


@dataclass
class ContractResult:
    outcomes: list[ContractOutcome] = field(default_factory=list)

    def kept(self) -> list[ContractOutcome]:
        return [o for o in self.outcomes if o.result == "routed"]

    def dropped(self) -> list[ContractOutcome]:
        return [o for o in self.outcomes if o.result != "routed"]


def load_proposals(path: Path) -> list[ContractProposal]:
    """Parse a Copilot-produced proposals file (a bare list or {"proposals": [...]})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("proposals", []) if isinstance(data, dict) else data
    out: list[ContractProposal] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        anchor = str(it.get("anchor") or it.get("excerpt") or "").strip()
        target = str(it.get("target") or "").strip()
        if not anchor or not target:
            continue  # an anchorless or targetless proposal can't be grounded
        out.append(ContractProposal(
            target=target,
            anchor=anchor,
            severity=str(it.get("severity") or "medium").strip().lower(),
            was=(str(it["was"]) if it.get("was") else None),
            rationale=(str(it["rationale"]) if it.get("rationale") else None),
            category=str(it.get("category") or "semantic-break").strip().lower(),
        ))
    return out


def _normalize_ref(target: str) -> str | None:
    """`"GET /api/v1/orders/{id}"` -> `"GET /api/v1/orders/{}"`, matching the diff facts' `ref`.
    None if the target isn't a `METHOD path` pair."""
    parts = target.split(None, 1)
    if len(parts) != 2:
        return None
    method, path = parts
    return f"{method.upper()} {openapi.normalize_path(path)}"


def _locate_in_current_spec(ctx: ScanContext, anchor: str) -> tuple[str, int, int] | None:
    """Find `anchor` as a contiguous run of whole lines in a CURRENT spec file (never the baseline —
    a semantic break must point at the new contract). Returns (relpath, start, end) 1-based inclusive."""
    needles = [ln.strip() for ln in anchor.splitlines() if ln.strip()]
    if not needles:
        return None
    prefix = openapi.BASELINE_DIR + "/"
    for path in ctx.files(*openapi._SPEC_GLOBS):
        rel = ctx.rel(path)
        if rel.startswith(prefix):
            continue
        stripped = [ln.strip() for ln in ctx.read_lines(rel)]
        for i in range(len(stripped) - len(needles) + 1):
            if all(needles[k] == stripped[i + k] for k in range(len(needles))):
                return rel, i + 1, i + len(needles)
    return None


def reground(ctx: ScanContext, proposals: list[ContractProposal]) -> ContractResult:
    """Locate -> refute -> route every proposal against the deterministic diff facts."""
    structural_refs = {f.attrs["ref"] for f in openapi.collect(ctx)
                       if f.type == "api.contract.change"}
    res = ContractResult()
    for p in proposals:
        loc = _locate_in_current_spec(ctx, p.anchor)
        if loc is None:
            res.outcomes.append(ContractOutcome(
                p, "unlocatable", note="anchor not found verbatim in the current spec"))
            continue
        rel, s, e = loc
        ref = _normalize_ref(p.target)
        if ref is not None and ref in structural_refs:
            res.outcomes.append(ContractOutcome(
                p, "refuted", rel, (s, e),
                note="the deterministic diff already flags this operation as a structural change"))
            continue
        evidence = ctx.evidence(rel, s, e, "llm.map_contracts", source_tier=LLM)
        res.outcomes.append(ContractOutcome(
            p, "routed", rel, (s, e), evidence,
            note="semantic break — no deterministic ground truth; routed to review"))
    return res


def run_map_contracts(
    target: str, *, proposals_path: str | Path | None = None
) -> ContractResult:
    """Scan `target`'s contract proposals and re-ground them. No proposals file -> empty result."""
    root = Path(target).resolve()
    if not root.exists():
        raise FileNotFoundError(f"target not found: {root}")
    ctx = ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)
    path = Path(proposals_path) if proposals_path else (root / PROPOSALS_REL)
    if not path.exists():
        return ContractResult()
    try:
        proposals = load_proposals(path)
    except (json.JSONDecodeError, OSError):
        return ContractResult()  # a malformed proposals file self-gates to "no proposals"
    return reground(ctx, proposals)
