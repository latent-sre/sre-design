---
name: sre-estate
description: 'Analyze cross-service reliability across MULTIPLE service repos at once: the estate topology and the co-tenancy blast radius of shared infrastructure (a datastore or broker many services depend on). Use when asked about cross-service impact, shared-database risk, what OTHER services are affected if shared infra fails, multi-service topology, or fleet/estate-level reliability. For the blast radius inside a single service, use sre-blast-radius instead. Keywords: estate, cross-service, co-tenancy, shared datastore, shared broker, topology, fleet, multi-repo, noisy neighbor, shared-infra blast radius.'
allowed-tools: ["codebase", "search", "editFiles", "runCommands"]
---

# SRE estate analysis

Most outages that surprise teams are **shared-infrastructure** outages: a database or broker
several services quietly co-tenant on. This skill turns the engine's estate run — a
`Topology` plus cross-service `BlastRadius` artifacts built from *multiple* repos — into a
fleet-level risk story. The engine derives co-tenancy from service-binding/shared-store
facts; you explain and prioritize it, grounded in each service's code.

## When to use this skill

- "If `orders-postgres` goes down, which services are affected?"
- "What infrastructure do we share, and who's the noisy neighbor?"
- "Give me the cross-service topology and the riskiest shared dependencies."

## Prerequisites

- Two or more locally-cloned service repos. Run the estate scan (each `--target` repeatable):

  ```bash
  sre-kb estate --target ../orders --target ../billing
  ```

  See [scripts/estate.sh](./scripts/estate.sh) for a thin wrapper. Output lands under
  `.work/<estate-run>/`: a `Topology` artifact, cross-service `BlastRadius` artifacts, and a
  `projections/diagrams/topology.mmd` Mermaid graph plus a GitHub-renderable `topology.md`
  (fenced Mermaid + legend).

## Workflow

1. Open the `Topology` artifact for the service/datastore/broker graph and the
   `topology.mmd` diagram for the picture. See
   [references/estate-fields.md](./references/estate-fields.md).
2. Find shared infra: nodes with **more than one** dependent service. For each, read the
   matching `BlastRadius` — its `coTenancy` lists the co-located tenants and `impactedServices`
   the fan-out.
3. Tell the co-tenancy story per shared node: "if `<store>` is down, `<services>` all degrade
   simultaneously; tenant `<X>`'s write path loses data (`dataLossRisk`)." Cite the binding /
   shared-store evidence per [references/provenance-rules.md](./references/provenance-rules.md).
4. Prioritize: a shared **stateful** node with `dataLossRisk` and many tenants is the top
   fleet risk. Recommend isolation (separate stores / bulkheads) or a shared-fate runbook.
5. Keep it grounded. Co-tenancy is asserted only where a binding/shared-store fact exists; if a
   coupling is suspected but unbacked, mark it "needs human confirmation," not a finding.

## Worked example

Running the estate over `order-service` + `billing-service`: the `Topology` shows both bind
`orders-postgres`, and the engine emits an `orders-postgres-cotenancy` BlastRadius with
`coTenancy: [{sharedBy: [billing-service, order-service]}]`, `impactedServices:
[billing-service, order-service]`, `stateful.dataLossRisk: true`, `severityHint: critical`.
Story: `orders-postgres` is a single point of failure for **two** teams — if it's down, both
services degrade *simultaneously* and in-flight data is at risk. That makes it the top fleet
risk, above anything contained within a single service. Fix: isolate the stores (per-service
databases), or — short of that — a shared-fate runbook and an alert that pages both owners.

## Gotchas

- **Estate radius ⊇ single-service radius.** A node contained *within* one service can still
  be a fleet risk if others share it without that containment. Compare per-service breakers.
- **Names must reconcile across repos.** Co-tenancy is keyed on the shared resource name (e.g.
  the bound service / datastore identifier). If two services name the same store differently,
  the engine can't link them — call out the naming gap rather than inventing the edge. HTTP
  `calls` edges resolve only when a client baseUrl hostname matches a scanned service's route;
  topics join only on the exact channel name.
- **Single-service vs estate.** A plain `sre-kb run` now emits that service's own `Topology`
  (rendered as `<service>-topology.mmd`/`.md`); cross-service joins (co-tenancy, resolved
  calls, producer/consumer topics) still need `sre-kb estate` with ≥2 targets.
