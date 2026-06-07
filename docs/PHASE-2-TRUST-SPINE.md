# Phase 2 — status-aware trust spine

Before Tier-B (LLM) facts mix into the graph, the trust gates have to understand *status*,
not just *existence*. The deep review (`HYBRID-PLAN.md` §4, "Gates not status-aware") found
three places where an unverified artifact could silently lend its trust to a verified one.
All three are closed here, each **downgrade-only** — these gates can lower trust, never raise
it, the same monotonic rule as the challenge pass.

## 1. Cross-references propagate trust (`validation/crossref.py`)

`check_crossrefs` used to resolve a reference if *any* artifact with that name existed. Now:

- **Existence** — a crossRef must still point at an artifact that exists (dangling = problem).
- **Trust propagation** — for a **trust-bearing** relation (`depends-on`, `implements` — where
  the citing artifact's correctness rests on the referent), the referent must itself be
  `verified`. Informational/reverse links (`alerts-on`, `covers`, `emits`, `mitigates`) only
  need to resolve — a verified `Flow` may `alerts-on` a needs-review `Alert` without inheriting
  its uncertainty.

`resolve_statuses(docs, status_of)` applies this to a **fixpoint**: downgrading a verified
artifact to needs-review can unverify a *third* artifact's referent, so it iterates until
stable. It terminates because `verified` only ever decreases.

The orchestrator is now two-phase: compute every artifact's *preliminary* status (structural +
provenance + safety + challenge, crossref deferred), then run `resolve_statuses` over those
statuses, then write each artifact at its settled status. This resolves the chicken-and-egg —
status-aware crossref needs the other artifacts' statuses, which weren't known when crossref
ran inline.

> **Why this matters for Tier B.** A `ResiliencyGap` is always `needs-review`. Without this
> gate, a verified artifact that `depends-on` a gap would keep its "verified" badge while
> resting on an unverified LLM proposal. Now it's downgraded — the gap can't launder trust.

## 2. Readiness credits only verified controls (`scoring/readiness.py`)

The PRR roll-up counted artifacts by *kind*: a `Runbook` existing made `runbook-for-top-flow`
pass even when that runbook was `needs-review`, inflating the grade. Now the artifact-backed
checks (`burn-rate-alert`, `alert-for-top-flow`, `runbook-for-top-flow`) credit the grade only
when the backing artifact is `verified`; a drafted-but-unverified control becomes a **gap**, not
a pass.

Effect on the bundled Spring sample: the only `Runbook` is `needs-review`, so the grade drops
from an inflated pass to **B (0.82)** with an explicit gap — "A Runbook exists but is not
verified". (The burn-rate `Alert` is verified, so `alert-for-top-flow` still passes honestly.)

## 3. Provenance confines cited paths (`validation/provenance.py`)

`root / path` had no confinement, so an edited or LLM-sourced citation could point at `../` or an
absolute path and **hash-match bytes outside the scanned repo**. The cited file must now resolve
*inside* the repo root (`is_relative_to`) before its hash is trusted; otherwise it fails with
"path escapes repo root". Harmless for engine output (always in-root) — load-bearing the moment a
human or an LLM edits an artifact's evidence.

## Tests

`tests/test_trust_spine.py` (9 tests): existence-only back-compat, verified-cannot-depend-on-
unverified, informational relations don't downgrade, cascade-to-fixpoint, dangling trust ref,
readiness not crediting unverified controls (alert + runbook), and provenance rejecting a path
that escapes the repo root while still accepting an in-root citation.

Full suite: 115 passing, ruff clean.
