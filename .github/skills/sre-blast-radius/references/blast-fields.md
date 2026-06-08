# BlastRadius artifact — field guide

One `BlastRadius` is emitted per failure-prone sink (an egress dependency, a broker, or a
datastore). The engine computes reachability and a **two-axis** risk from facts; read these
fields to tell the impact story. Do not edit the computed values — enrich the narrative
around them. Field shapes below match what the engine actually emits.

```yaml
kind: BlastRadius
spec:
  node: { type: service|broker|datastore, name: inventory }
  impactedFlows: [create-order, ...]     # flows that fail/degrade if the node is down
  impactedServices: [billing-service, …] # populated by estate runs (cross-service)
  containment:                           # cross-refs to the mechanisms that absorb the failure
    - { kind: ResiliencyPattern, name: inventory }
    - { kind: Fallback, name: reserve-fallback }
  coTenancy:                             # estate runs only: who shares this node
    - { sharedBy: [billing-service, order-service] }
  stateful: { dataLossRisk: true }       # datastore/broker: is in-flight data lost?
  dependencyCriticality: critical        # critical | degraded   (consequence axis)
  severityHint: high                     # low | medium | high   (blast-scale axis; estate may emit critical)
  riskRationale: "severity=high: 1 impacted flow, irreversible data loss on failure"
```

## The two axes (don't conflate them)

- **`dependencyCriticality`** = the *consequence* to the impacted flows:
  - `critical` — no bulkhead: a failure fails the flow, or loses data.
  - `degraded` — a circuit breaker / fallback lets the flow continue in a degraded mode.
- **`severityHint`** = the overall *blast scale*: `low|medium|high`, rising with how many flows
  are hit and whether the failure is irreversible (data loss). A contained dependency on one
  flow is `medium`; an uncontained or data-losing one, or one fanning out across flows, is
  `high`. The cross-service co-tenancy path can raise it to `critical`.

`riskRationale` is the engine's one-line explanation of the number — quote it; don't invent a
different justification.

## How to read it

- **`containment` non-empty** → contained; name the `Fallback`/`ResiliencyPattern` it points to.
  The breaker/fallback's code location is in this artifact's top-level `evidence[]` (cite that),
  not inside the containment entries — those are cross-refs to the named artifacts.
- **`dependencyCriticality: critical` + `containment: []`** → uncontained; a failure propagates
  straight to the caller. Launch-blocking.
- **`stateful.dataLossRisk: true`** → in-flight data is lost on failure (logged-and-swallowed
  write/publish). Worst case; lead with it. If RPO/RTO facts exist, express impact as recovery
  time, not just "down."
- **`coTenancy` non-empty** → a shared node; every service in `sharedBy` fails at once. Only
  estate runs populate this — see the `sre-estate` skill.

## Mapping to `sre-kb findings`

`sre-kb findings` ranks these into three finding types: `data-loss-risk` (from
`stateful.dataLossRisk`), `uncontained-critical-dep` (`dependencyCriticality: critical` + empty
`containment`), and `broad-impact-dependency` (`severityHint: high` but contained). Use the
digest to prioritize, then open the artifact for the evidence.
