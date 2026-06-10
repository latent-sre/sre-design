# Estate artifacts — field guide

An estate run (`sre-kb estate --target A --target B ...`) builds two things from the merged
facts of several repos.

## `Topology`

Field shapes for every kind live in the generated
[docs/SCHEMA-REFERENCE.md](../../../../docs/SCHEMA-REFERENCE.md); this file carries the
semantics. The cross-service graph: services, the datastores/brokers they bind to, the messaging
topics they publish/consume, and the downstreams they call. Rendered to
`projections/diagrams/topology.mmd` plus a GitHub-renderable `topology.md` (fenced Mermaid
with a shape legend). Read it to spot **shared infrastructure** — any datastore/broker/topic
node with more than one attached service.

```yaml
kind: Topology
spec:
  nodes: [ { type: service|datastore|broker|topic|resource|library|external, name: orders-postgres }, ... ]
  edges: [ { from: order-service, to: orders-postgres, relation: binds }, ... ]
  # relation: binds | calls | publishes | consumes | uses-library
  pcfSpaces: []
```

Three joins make the edges real, not just declared:

- **`calls` edges resolve across repos** — a `clients.*.base-url` whose hostname matches
  another scanned service's PCF route becomes a `service -> service` edge; an unmatched
  hostname stays an `external` node (call out the naming gap, don't invent the edge).
- **`topic` nodes join producers to consumers** — a channel one repo publishes and another
  consumes appears once, with `publishes`/`consumes` edges on each side. "Who consumes
  `order.created`?" is read straight off the graph.
- **`library` nodes join shared internal code** — dependencies matching the configured
  `estate.internal_namespaces` globs (e.g. `com.acme*`, `@acme/*`) become `uses-library`
  edges, so "which repos does a change to this library blast into?" reads off the graph.
  When two services pin different versions, the estate report carries a
  `library-version-skew` finding.

## Cross-service `BlastRadius`

Like the single-service `BlastRadius`, but populated across repos: `impactedServices` and
`coTenancy` span every tenant, and `impactedFlows` lists each tenant's affected flows as
`service/flow` (joined from each repo's flow sinks):

- **`coTenancy`** — a list of `{ sharedBy: [services] }`: the services co-located on this
  shared resource. A non-empty list means a failure here is a *simultaneous* multi-service event.
- **`impactedServices`** — every service that degrades if this node is down.
- **`impactedFlows`** — the concrete flows behind that fan-out, qualified per service
  (e.g. `order-service/create-order`).
- **`stateful.dataLossRisk`** — for a shared datastore/broker, whether a tenant loses in-flight
  data. The co-tenancy path can raise `severityHint` to `critical`.

## Prioritizing fleet risk

Rank shared nodes by: (1) `dataLossRisk` true, (2) number of co-tenants / impacted services,
(3) `severityHint`. A shared stateful node with data-loss risk and many tenants is the top
fleet-level risk — it's a single point of failure for several teams at once. The fix is
usually isolation (per-service stores, bulkheads) or, short of that, a shared-fate runbook and
an alert that pages every owning team.
