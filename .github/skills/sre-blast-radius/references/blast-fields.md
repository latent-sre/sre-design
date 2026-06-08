# BlastRadius artifact — field guide

One `BlastRadius` is emitted per failure-prone sink (an egress dependency or a datastore).
The engine computes the reachability and severity from facts; read these fields to tell the
impact story. Do not edit the computed values — enrich the narrative around them.

```yaml
kind: BlastRadius
spec:
  node: { type: service|datastore|broker, name: inventory-service }
  impactedFlows: [place-order, ...]      # flows that fail/degrade if node is down
  impactedServices: [orders, ...]        # services touched (estate runs populate this)
  containment:                           # what absorbs the failure (breaker/fallback/bulkhead)
    - { type: circuit-breaker, evidence: "...:42" }
  coTenancy: [...]                        # other tenants on a shared store (estate runs)
  stateful: { dataLossRisk: true }       # datastore nodes: is in-flight data lost?
  dependencyCriticality: critical        # critical | high | normal
  severityHint: critical                 # low | medium | high | critical
```

## How to read it

- **`impactedFlows` empty + `containment` present** → contained; an outage is a degraded path,
  not an outage. Say which fallback carries it (cite the evidence line).
- **`dependencyCriticality: critical` + `containment: []`** → uncontained critical dep; a
  failure propagates straight to the caller. This is a launch-blocking finding.
- **`stateful.dataLossRisk: true`** → the node loses in-flight data on failure (logged-and-
  swallowed write/publish). Worst case; lead with it. If RPO/RTO are present, express impact
  as recovery time, not just "down."
- **`coTenancy` non-empty** → a shared store; a failure hits every listed tenant at once. Only
  estate runs populate this — see the `sre-estate` skill.

## Mapping to `sre-kb findings`

`sre-kb findings` ranks these into three finding types: `data-loss-risk` (from
`stateful.dataLossRisk`), `uncontained-critical-dep` (critical + no containment), and
`broad-impact-dependency` (high severity but contained). Use the digest to prioritize, then
open the artifact for the evidence.
