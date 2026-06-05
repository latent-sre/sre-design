"""Gating (layer d): decide the final status. Nothing is dropped — failures downgrade
to needs-review (or rejected for structural failures) and are reported."""

from __future__ import annotations


def final_status(
    doc: dict,
    *,
    structural_ok: bool,
    provenance_ok: bool,
    crossref_ok: bool,
    min_confidence: float,
    require_verified_provenance: bool,
) -> str:
    if not structural_ok:
        return "rejected"
    status = doc.get("status", "needs-review")
    if status != "verified":
        return status
    has_ev = bool(doc.get("evidence"))
    conf = doc.get("confidence")
    if require_verified_provenance and (not has_ev or not provenance_ok):
        return "needs-review"
    if not crossref_ok:
        return "needs-review"
    if conf is None or conf < min_confidence:
        return "needs-review"
    return "verified"
