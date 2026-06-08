"""Apply LLM challenge verdicts (produced by Copilot from the worklist) and re-gate the
affected artifacts. The oracle only proposes verdicts; this module applies the SAME
monotonic downgrade-only gating as the deterministic pass, then moves each artifact file
to its new status directory. The engine stays the decision-maker."""

from __future__ import annotations

import yaml

from sre_kb.validation.challenge import apply_challenge_gating, parse_verdicts
from sre_kb.workspace import RunLayout


def _index(layout: RunLayout) -> dict[tuple[str, str], tuple]:
    index: dict[tuple[str, str], tuple] = {}
    for root in (layout.kb / "verified", layout.kb / "needs-review", layout.reports / "rejected"):
        if not root.exists():
            continue
        for path in root.rglob("*.yaml"):
            doc = yaml.safe_load(path.read_text())
            index[(doc["kind"], doc["metadata"]["name"])] = (path, doc)
    return index


def _dest_dir(layout: RunLayout, status: str, kind: str):
    base = (layout.reports / "rejected" / kind) if status == "rejected" else (layout.kb_dir(status) / kind)
    base.mkdir(parents=True, exist_ok=True)
    return base


def apply_verdicts(layout: RunLayout, data: dict) -> list[dict]:
    """Re-gate artifacts named in `data['verdicts']`; returns a per-artifact summary."""
    index = _index(layout)
    summary: list[dict] = []
    for artifact, verdicts in parse_verdicts(data).items():
        kind, _, name = artifact.partition("/")
        entry = index.get((kind, name))
        if entry is None:
            summary.append({"artifact": artifact, "result": "not-found"})
            continue
        path, doc = entry
        old = doc.get("status", "needs-review")
        new, notes = apply_challenge_gating(old, verdicts)
        # Idempotent: challenge-apply is a re-runnable human-in-the-loop step, so merge verdicts by
        # claimId (latest wins) instead of blindly appending — re-running must not duplicate the
        # audit trail. Gating is monotonic regardless; this keeps the persisted record honest.
        merged = {e.get("claimId"): e for e in doc.get("challengeVerdicts", [])}
        for v in verdicts:
            merged[v.claim_id] = {"claimId": v.claim_id, "verdict": v.verdict, "reason": v.reason}
        doc["challengeVerdicts"] = list(merged.values())
        doc["status"] = new
        dest = _dest_dir(layout, new, kind) / f"{name}.yaml"
        dest.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
        if dest != path:
            path.unlink()
        summary.append({"artifact": artifact, "old": old, "new": new, "notes": notes})
    return summary
