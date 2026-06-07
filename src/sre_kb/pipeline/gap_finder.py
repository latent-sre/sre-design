"""Gap-finder pipeline (HYBRID-PLAN §7.9/§7.10) — drive the Tier-B loop and gate it.

Scaffold each re-grounded gap Fact into a `ResiliencyGap` artifact, then run the SAME validation
the engine runs on everything (structural schema + provenance hash-check + final-status gate).
The contract — nothing LLM-proposed can auto-verify — is enforced three ways: the scaffold sets
`status="needs-review"`, confidence is below the verified floor, and `unverifiedAgainstLive` marks
the absence as not checkable offline.

The engine still never calls a model: it ingests proposals Copilot already wrote.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.llm import gap_finder
from sre_kb.collectors.llm.gap_finder import GapResult
from sre_kb.config import load_config
from sre_kb.models.facts import Fact
from sre_kb.scoring.confidence import Signal, confidence
from sre_kb.synth.emit import emit
from sre_kb.tiers import AST
from sre_kb.util import slug
from sre_kb.validation.gating import final_status
from sre_kb.validation.provenance import verify_evidence
from sre_kb.validation.structural import validate_doc


def scaffold_gap(fact: Fact, service: str) -> dict:
    """One re-grounded gap Fact -> a ResiliencyGap artifact.

    Two tiers (§9.4): a refutation-probe gap is `source_tier=llm` and is fenced — `needs-review`,
    sub-floor confidence, `llm-asserted`, never auto-verified. A confirmation-probe gap the engine
    re-derived deterministically at the pointer is `source_tier=ast` (GRADUATED): it goes through
    the normal gate as a Tier-A finding (can reach `verified`), exactly like any engine-extracted
    fact — the LLM only widened *where* the deterministic rule ran.
    """
    a = fact.attrs
    tier = fact.evidence.source_tier
    name = slug(f"{a['target']}-{a['category']}")
    if tier == AST:  # graduated: engine-derived, not LLM-asserted
        status, conf, prov, unverified, cross = "verified", confidence(Signal.DIRECT), "deterministic", False, None
    else:
        status, conf, prov, unverified = "needs-review", confidence(Signal.WEAK), "llm-asserted", True
        cross = ([{"kind": "ResiliencyPattern", "name": slug(a["target"]), "relation": "depends-on"}]
                 if a.get("target") else None)
    return emit(
        "ResiliencyGap",
        name,
        {
            "category": a["category"],
            "target": a.get("target"),
            "severity": a.get("severity", "medium"),
            "rationale": a.get("rationale"),
            "rederivation": a.get("rederivation", "confirmed"),
            "sourceTier": tier,
            "checked": a.get("checked", []),
        },
        [fact.evidence],
        status,
        conf,
        service,
        cross_refs=cross,
        provenance=prov,
        unverified_against_live=unverified,
    )


@dataclass
class GapRunResult:
    result: GapResult
    docs: list[dict]
    by_status: dict[str, int]
    records: list[dict]


def run_gap_finder(
    target: str, *, proposals_path: str | Path | None = None, service: str | None = None
) -> GapRunResult:
    """Scan `target`'s LLM gap proposals, re-ground them, scaffold + validate + gate."""
    full_cfg = load_config()
    cfg = full_cfg.get("gating", {})
    cap = (full_cfg.get("gap_finder") or {}).get("max_candidates")
    root = Path(target).resolve()
    if not root.exists():
        raise FileNotFoundError(f"target not found: {root}")
    ctx = ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)
    svc = service or root.name

    result = gap_finder.collect(
        ctx, Path(proposals_path) if proposals_path else None, max_candidates=cap
    )

    docs, records = [], []
    by_status: dict[str, int] = {}
    for f in result.facts:
        doc = scaffold_gap(f, svc)
        struct = validate_doc(doc)
        prov = verify_evidence(doc, root)
        status = final_status(
            doc,
            structural_ok=not struct,
            provenance_ok=not prov,
            crossref_ok=True,
            min_confidence=cfg.get("verified_min_confidence", 0.7),
            require_verified_provenance=cfg.get("require_verified_provenance", True),
        )
        doc["status"] = status
        docs.append(doc)
        by_status[status] = by_status.get(status, 0) + 1
        records.append({"artifact": f"ResiliencyGap/{doc['metadata']['name']}",
                        "status": status, "structural": struct, "provenance": prov})
    return GapRunResult(result, docs, by_status, records)
