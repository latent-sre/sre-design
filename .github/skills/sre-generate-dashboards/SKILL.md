---
name: sre-generate-dashboards
description: >-
  Generate-phase (Tier-B) dashboard drafter — extend the engine's baseline RED overview with the
  golden-signal panels it can't infer (saturation, per-dependency latency/errors, async queue depth),
  each grounded in a metric/dependency fact the engine already detected. Use when asked to draft or
  improve a service's dashboard, add panels, or close monitoring-coverage gaps. Every panel lands
  needs-review + unverifiedAgainstLive: you propose panels from real metrics, the engine renders the
  per-source query and never claims live verification. Keywords: dashboard, panel, RED, golden signals,
  saturation, monitoring coverage, Grafana, Prometheus, observability.
allowed-tools: ["codebase", "search", "editFiles", "runCommands"]
metadata:
  version: 0.1.0
---

# sre-generate-dashboards

The engine already scaffolds a baseline **RED** overview (Rate / Errors / Duration) for a service's
top flow. This skill **widens panel coverage** — proposing the golden-signal panels a deterministic
scaffold can't know to add — each grounded in a metric the service actually emits.

## When to use this skill

- "Draft / improve the dashboard for this service."
- "What panels are missing from the overview?"
- After `sre-flow-analysis` and (ideally) `sre-observability-coverage`, when the scaffolded
  `Dashboard` candidate has only the baseline RED panels.

## Prerequisites

- A scaffolded run exists; the engine has emitted a `Dashboard` candidate (the RED overview) and the
  `Observability` facts that prove which metrics exist.

## The trust boundary (read this first)

You widen panel coverage; the engine owns the query and the verification status:

1. **Propose panels from metrics that exist.** A panel's `signal.metric` must be a metric the
   `Observability` facts prove the service emits (e.g. a Micrometer
   `http_server_requests_seconds_*`, a JVM/process gauge, a pool-saturation metric). Never invent a
   metric name to justify a panel — read [references/dashboard-fields.md](./references/dashboard-fields.md).
2. **The engine renders the query.** Give the tool-neutral `signal` (source + metric + a one-line
   description of what it shows); the per-source `query` is the engine's to generate faithfully
   (`render/dashboards.py`). Don't hand-write a vendor query you can't ground.
3. **Every panel stays `needs-review` + `unverifiedAgainstLive`.** A drafted dashboard is a
   suggestion whose queries fire against live metrics no one has confirmed. You cannot mark it
   `verified` or drop the `unverifiedAgainstLive` flag.

## Workflow

1. Read the scaffolded `Dashboard` candidate's baseline RED panels — do **not** duplicate them.
2. For each gap a golden-signal review surfaces, add a panel grounded in a real metric:
   - **Saturation** — a thread-pool / connection-pool / queue / heap metric the service emits.
   - **Per-dependency latency & errors** — for each downstream HTTP egress or datastore the facts
     show, a panel on the client's request metric, scoped to that dependency.
   - **Async** — for a message producer/consumer, a queue-depth or consumer-lag panel if the metric
     exists.
   Cite the fact (the egress call, the datastore binding, the actuator/metric config) the panel
   visualizes.
3. Obey [references/provenance-rules.md](./references/provenance-rules.md): a panel may reference
   only metrics that appear in the facts; unknown ⇒ leave it out (or note the coverage gap for
   `sre-observability-coverage`), never fabricate.
4. Run `sre-kb run --target <repo> --run <id> --to-stage validate` and fix flagged items until the
   `Dashboard` is a clean `needs-review`.

## Gotchas

- **Don't restate RED.** The baseline already has Rate/Errors/Duration for the primary route; add
  the panels it lacks (saturation, per-dependency, async), not a second copy.
- **No metric, no panel.** If a saturation signal isn't in the `Observability` facts, the honest
  output is a coverage gap (hand it to `sre-observability-coverage`), not an invented metric.
- **One signal per panel.** Keep each panel a single tool-neutral `signal`; let the engine fan it
  out across render targets rather than stacking vendor queries.
- **`renderTarget` is one backend.** A `Dashboard` renders to one of prometheus/splunk/wavefront/
  appdynamics/grafana; don't mix sources within a dashboard unless you intend a second artifact.
- The model is unset on purpose (LLM-neutral) — this skill works under any Copilot model.
