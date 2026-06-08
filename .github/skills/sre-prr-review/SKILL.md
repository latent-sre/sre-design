---
name: sre-prr-review
description: 'Grade a service''s production readiness (PRR) from sre-kb facts and turn the gaps into a prioritized, code-grounded remediation plan. Use when asked to assess production readiness, run a PRR / launch review, score reliability maturity, or explain why a service is not ready to ship. Keywords: production readiness, PRR, launch review, readiness score, reliability scorecard, SLO, runbook coverage, go/no-go.'
---

# SRE production-readiness review

Turn the engine's deterministic `ReadinessScore` artifact into a **grounded PRR verdict**:
a grade, the specific failing checks, and a remediation plan where every gap points at the
code (or the missing code) that causes it. You add judgment and prioritization; you never
invent a check result — the engine computes the checks from facts.

## When to use this skill

- "Is this service ready for production / what's its PRR grade?"
- "What do we need to fix before launch, in priority order?"
- "Why is the readiness score a C and not an A?"

## Prerequisites

- A validated run exists: `sre-kb run --target <repo> --to-stage validate` (or use an
  existing `--run <id>`). The `ReadinessScore` lands under `.work/<run>/kb/<status>/ReadinessScore/`.

## Workflow

1. Read the `ReadinessScore` artifact. Its `spec.prrChecks` is a map of check → bool, with
   a `spec.score` (0–1), `spec.grade` (A–F), `spec.coverage` roll-up, and `spec.gaps`. See
   [references/prr-checks.md](./references/prr-checks.md) for what each check means and the
   fact/kind that backs it.
2. **Do not re-decide the booleans.** They are derived from provenance-backed facts. Your
   job is to explain, prioritize, and propose the fix — grounded in
   [references/provenance-rules.md](./references/provenance-rules.md).
3. For each failing check, write a remediation item: the **risk** (what breaks in prod),
   the **fix** (cite the `path:line` to change, or name the missing artifact), and a
   **priority** driven by blast radius — cross-reference the `sre-kb findings` digest and
   any `BlastRadius` with `severityHint: high`/`critical` so the most impactful gaps rank first.
4. Produce a **go / no-go** with conditions: which gaps are launch-blocking (e.g. no SLO,
   no runbook for the top flow, a swallowed data-loss path) vs. fast-follow.
5. If your assessment narrative makes a claim about the code (e.g. "the egress call has no
   timeout"), it must be a check the engine already verified or a `path:line` you can cite.
   Unknown ⇒ say "needs human confirmation", never assert.

## Prioritization rules

- **Launch-blocking by default:** no SLO/objective, a `dataLossRisk` flow step, a critical
  dependency with no containment, or no runbook for the top flow.
- **Rank by blast radius.** A missing breaker on a node that fans out to many flows outranks
  one on a leaf. Read `severityHint` and `impactedFlows` from the `BlastRadius` artifacts.
- **Tracing/structured-logging gaps are rarely blocking** on their own — flag as fast-follow
  unless an incident would be undiagnosable without them.

## Gotchas

- **A grade is not a gate.** The grade summarizes coverage; the *findings* (data-loss,
  uncontained critical deps) are what actually block a launch. Lead with those.
- **`tracing-enabled: false` is common and expected** for Spring/Actuator services without
  Sleuth/OTel — note it, don't treat it as a defect unless it blocks diagnosis.
- **No SLO → no burn-rate alert → a capped score.** That chain is intentional; the fix is to
  define the objective (a human decision), not to invent a threshold.
