# Dashboard artifact — field guide

```yaml
kind: Dashboard
spec:
  title: <service> — service overview (RED)
  renderTarget: prometheus | splunk | wavefront | appdynamics | grafana   # one backend
  panels:
    - title: <what it shows>                  # e.g. "Connection pool saturation"
      type: timeseries | stat | gauge | table | heatmap
      unit: req/s | percentunit | s | ...
      signal:
        source: prometheus | splunk | wavefront | appdynamics | grafana
        metric: <a metric the service actually emits>   # grounded in Observability facts
        description: <one line: what the panel measures>
        query: <ENGINE-GENERATED — leave to render/dashboards.py>
```

**The three golden signals beyond baseline RED**

The scaffold already emits Rate / Errors / Duration for the primary route. Add what it can't infer:

- **Saturation** — how full a bounded resource is: thread-pool active/queued, connection-pool
  in-use vs max, heap/old-gen, message-queue depth. Use the metric the runtime actually exposes
  (e.g. a Micrometer `executor_*`, `hikaricp_connections_*`, `jvm_memory_used_bytes`).
- **Per-dependency latency & errors** — one panel per downstream the facts show (HTTP egress client,
  datastore), on that client's request metric scoped to the dependency.
- **Async** — queue depth / consumer lag for a detected producer or consumer, when the metric exists.

**What good looks like**

- `signal.metric` names a metric present in the `Observability` facts — never invented.
- `query` is left for the engine; you supply source + metric + description.
- `crossRefs` link the `Dashboard` to the `Flow` (and `Dependency`/`DataStore`) it covers.
- `status: needs-review`, `unverifiedAgainstLive: true` — a suggested dashboard, not a confirmed one.
