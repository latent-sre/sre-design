"""Cross-reference validation (layer c): every crossRef must resolve to an artifact, and a
verified artifact must not rest on unverified foundations (the trust spine is status-aware)."""

from __future__ import annotations

# Relations where the citing artifact's trust genuinely depends on the referent. Back-links
# (alerts-on, covers, emits) do NOT downgrade the citer — an alert needing review doesn't make
# the flow it watches unverified.
_TRUST_DEPS = {"depends-on", "implements"}


def check_crossrefs(docs: list[dict]) -> dict[str, list[str]]:
    index = {(d.get("kind"), (d.get("metadata") or {}).get("name")) for d in docs}
    problems: dict[str, list[str]] = {}
    for d in docs:
        name = (d.get("metadata") or {}).get("name")
        errs: list[str] = []
        for ref in d.get("crossRefs") or []:
            rname = ref.get("name")
            if rname in (None, "", "-"):
                continue
            if (ref.get("kind"), rname) not in index:
                errs.append(f"dangling crossRef -> {ref.get('kind')}/{rname}")
        if errs:
            problems[f"{d.get('kind')}/{name}"] = errs
    return problems


def status_aware_downgrades(
    status_by_key: dict[str, str], crossrefs_by_key: dict[str, list[dict]]
) -> dict[str, str]:
    """A verified artifact that depends-on/implements a non-verified (or missing) referent is
    downgraded to needs-review, so a "verified" graph never rests on unverified foundations
    (HYBRID-PLAN §4/Phase 2). Iterated to a fixpoint (monotonic, downgrade-only) so a downgrade
    cascades to whatever depends on it. Returns {key: reason} for each downgraded artifact."""
    verified = {k for k, s in status_by_key.items() if s == "verified"}
    reasons: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for k in list(verified):
            for ref in crossrefs_by_key.get(k, []):
                if ref.get("relation") not in _TRUST_DEPS:
                    continue
                name = ref.get("name")
                if name in (None, "", "-"):
                    continue
                rk = f"{ref.get('kind')}/{name}"
                if rk not in verified:
                    verified.discard(k)
                    reasons[k] = f"depends on non-verified {rk}"
                    changed = True
                    break
    return reasons
