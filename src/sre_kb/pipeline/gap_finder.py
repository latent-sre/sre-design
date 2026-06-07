"""Gap-finder pipeline (SPIKE) — drive the Tier-B loop end to end and gate it.

This mirrors the deterministic orchestrator for the one new collector: scaffold each
re-grounded gap Fact into a `ResiliencyGap` artifact, then run the SAME validation +
gating the engine runs on everything (structural schema + provenance hash-check + final
status gate). The contract — nothing LLM-proposed can auto-verify — is enforced twice:
the scaffold sets `status="needs-review"`, and confidence is below the verified floor.

The engine still never calls a model: it ingests proposals the LLM already wrote.
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
from sre_kb.util import slug
from sre_kb.validation.gating import final_status
from sre_kb.validation.provenance import verify_evidence
from sre_kb.validation.structural import validate_doc


def scaffold_gap(fact: Fact, service: str) -> dict:
    """One re-grounded gap Fact -> a ResiliencyGap artifact, fenced to needs-review."""
    a = fact.attrs
    name = slug(f"{a['target']}-{a['pattern']}-gap")
    return emit(
        "ResiliencyGap",
        name,
        {
            "pattern": a["pattern"],
            "target": a.get("target"),
            "severity": a.get("severity", "medium"),
            "rationale": a.get("rationale"),
            "rederivation": a.get("rederivation", "confirmed"),
            "sourceTier": fact.source_tier,
        },
        [fact.evidence],
        "needs-review",          # contract: an LLM-proposed gap can never auto-verify
        confidence(Signal.WEAK),  # 0.5 — below the verified floor even if status were raised
        service,
        cross_refs=([{"kind": "ResiliencyPattern", "name": slug(a["target"]), "relation": "depends-on"}]
                    if a.get("target") else None),
        provenance="llm-asserted",
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
    cfg = load_config().get("gating", {})
    root = Path(target).resolve()
    if not root.exists():
        raise FileNotFoundError(f"target not found: {root}")
    ctx = ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)
    svc = service or root.name

    result = gap_finder.collect(ctx, Path(proposals_path) if proposals_path else None)

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
