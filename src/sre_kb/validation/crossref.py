"""Cross-reference validation (layer c): every crossRef must resolve to an artifact, and a
*verified* artifact may not depend on an unverified one.

Two checks, both downgrade-only:
  - existence: a crossRef must point at an artifact that exists (no dangling references).
  - trust propagation: for a TRUST-BEARING relation (`depends-on`/`implements` — the citing
    artifact's correctness rests on the referent), the referent must itself be `verified`.
    Otherwise a "verified" artifact could inherit trust from an unverified (e.g. Tier-B,
    needs-review) one, inflating the graph. Informational/reverse links (`alerts-on`,
    `covers`, `emits`, `mitigates`) only need to resolve.

`status_of` is optional: without it, only existence is checked (back-compatible). The
orchestrator passes preliminary statuses and re-checks to a fixpoint so downgrades cascade.
"""

from __future__ import annotations

# Relations where the citing artifact's correctness depends on the referent being correct.
TRUST_BEARING = {"depends-on", "implements"}


def check_crossrefs(
    docs: list[dict], status_of: dict[tuple, str] | None = None
) -> dict[str, list[str]]:
    index = {(d.get("kind"), (d.get("metadata") or {}).get("name")) for d in docs}
    problems: dict[str, list[str]] = {}
    for d in docs:
        name = (d.get("metadata") or {}).get("name")
        errs: list[str] = []
        for ref in d.get("crossRefs") or []:
            rname = ref.get("name")
            if rname in (None, "", "-"):
                continue
            rkey = (ref.get("kind"), rname)
            if rkey not in index:
                errs.append(f"dangling crossRef -> {ref.get('kind')}/{rname}")
                continue
            if status_of is not None and ref.get("relation") in TRUST_BEARING:
                rstatus = status_of.get(rkey, "needs-review")
                if rstatus != "verified":
                    errs.append(
                        f"unverified referent -> {ref.get('kind')}/{rname} [{rstatus}]"
                    )
        if errs:
            problems[f"{d.get('kind')}/{name}"] = errs
    return problems


def resolve_statuses(docs: list[dict], status_of: dict[tuple, str]) -> dict[str, list[str]]:
    """Downgrade-only fixpoint over `status_of` (mutated in place): a verified artifact whose
    trust-bearing crossRef is unverified or dangling is dropped to needs-review, which may
    unverify a *third* artifact's referent — so iterate until stable. Returns the final
    crossRef problems. Terminates because `verified` only ever decreases."""
    while True:
        problems = check_crossrefs(docs, status_of)
        changed = False
        for d in docs:
            tkey = (d.get("kind"), (d.get("metadata") or {}).get("name"))
            if problems.get(f"{tkey[0]}/{tkey[1]}") and status_of.get(tkey) == "verified":
                status_of[tkey] = "needs-review"
                changed = True
        if not changed:
            return problems
