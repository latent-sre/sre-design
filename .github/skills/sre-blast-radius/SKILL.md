---
name: sre-blast-radius
description: 'Reason about what fails when a dependency or datastore goes down, using the engine''s BlastRadius and ResiliencyPattern facts, and sharpen the severity / containment narrative grounded in code. Use when asked what breaks if X is down, how far an outage spreads, whether a failure is contained, what the blast radius or impact of a dependency is, or to prioritize risks by impact. Keywords: blast radius, impact, what breaks if down, circuit breaker, bulkhead, containment, data loss, critical dependency, severity.'
---

# SRE blast-radius analysis

Turn the engine's `BlastRadius` artifacts (one per failure-prone sink — an egress
dependency or a datastore) into a **clear impact story**: if this node is down, which flows
and services degrade, what the circuit breaker contains, and whether data is lost. The
engine computes reachability and a `severityHint` deterministically; you enrich the
narrative and verify the severity is justified — never invent impact.

## When to use this skill

- "What breaks if `inventory-service` (or `orders-postgres`) goes down?"
- "Is this dependency failure contained, or does it propagate to the caller?"
- "Rank our reliability risks by impact."

## Prerequisites

- A validated run: `sre-kb run --target <repo> --to-stage validate`. `BlastRadius` artifacts
  land under `.work/<run>/kb/<status>/BlastRadius/`; the ranked digest is `sre-kb findings`.

## Workflow

1. Run `sre-kb findings --run <id>` for the ranked, severity-ordered digest, then open the
   underlying `BlastRadius` artifacts. See [references/blast-fields.md](./references/blast-fields.md)
   for what each field means.
2. For each node, state the impact in operator terms: **impactedFlows** (which request paths
   fail), **impactedServices**, what `containment` (breaker/fallback) absorbs, and — for a
   datastore/broker — `stateful.dataLossRisk` plus RPO/RTO if present.
3. **Verify the risk, don't restate it.** The engine reports two axes (see
   [references/blast-fields.md](./references/blast-fields.md)): `dependencyCriticality`
   (`critical` = no bulkhead / data loss, `degraded` = continues degraded) and `severityHint`
   (`low|medium|high`, scaling with breadth + irreversibility). Quote the engine's
   `riskRationale` and cross-check it against the facts; cite the breaker/fallback location
   from the artifact's top-level `evidence[]` (per
   [references/provenance-rules.md](./references/provenance-rules.md)) when you call something
   contained — the `containment` entries are cross-refs (`{kind, name}`), not the evidence.
4. Translate to action: the highest-impact uncontained node is where a breaker/fallback or an
   outbox/retry should go. Tie each recommendation to the node and its evidence.
5. For judgment calls the facts can't settle (is this severity *appropriate*?), use the
   challenge loop — see [references/challenge-protocol.md](./references/challenge-protocol.md).

## Severity discipline

- **`dependencyCriticality: critical`** — no bulkhead: a failure fails the flow or loses data.
  This is the launch-blocking axis.
- **`severityHint: high`** — broad/irreversible blast: many flows hit, or data lost, even if a
  bulkhead is present. The cross-service co-tenancy path can raise it to `critical`.
- **data-loss beats availability.** A swallowed publish/write failure (`dataLossRisk: true`)
  is the worst case even if the node looks "up" — surface it first; it never silently heals.

## Gotchas

- **Containment is only as good as its evidence.** If you can't cite the breaker/fallback in
  code, treat the node as *uncontained* and say so — don't assume the annotation exists.
- **Single-service vs. estate.** A per-repo run gives single-service radius; cross-service
  co-tenancy (shared datastore blast radius across repos) comes from `sre-kb estate` — use the
  `sre-estate` skill for that.
- **Don't inflate severity for emphasis.** The gate downgrades, never upgrades; an
  unjustified `critical` just adds noise. Match the severity to the cited facts.
