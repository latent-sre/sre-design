# Estate artifacts — field guide

An estate run (`sre-kb estate --target A --target B ...`) builds two things from the merged
facts of several repos.

## `Topology`

The cross-service graph: services, the datastores/brokers they bind to (and external deps
they call), and the edges between them. Rendered to `projections/diagrams/topology.mmd`
(Mermaid). Read it to spot **shared infrastructure** — any datastore/broker node with more
than one inbound service.

```yaml
kind: Topology
spec:
  nodes: [ { type: service|datastore|broker|external, name: orders-postgres }, ... ]
  edges: [ { from: order-service, to: orders-postgres, relation: binds }, ... ]  # relation: binds | calls
  pcfSpaces: []
```

## Cross-service `BlastRadius`

Like the single-service `BlastRadius`, but `impactedServices` and `coTenancy` are populated
across repos (and `impactedFlows` is typically empty — the impact is expressed per service):

- **`coTenancy`** — a list of `{ sharedBy: [services] }`: the services co-located on this
  shared resource. A non-empty list means a failure here is a *simultaneous* multi-service event.
- **`impactedServices`** — every service that degrades if this node is down.
- **`stateful.dataLossRisk`** — for a shared datastore/broker, whether a tenant loses in-flight
  data. The co-tenancy path can raise `severityHint` to `critical`.

## Prioritizing fleet risk

Rank shared nodes by: (1) `dataLossRisk` true, (2) number of co-tenants / impacted services,
(3) `severityHint`. A shared stateful node with data-loss risk and many tenants is the top
fleet-level risk — it's a single point of failure for several teams at once. The fix is
usually isolation (per-service stores, bulkheads) or, short of that, a shared-fate runbook and
an alert that pages every owning team.
