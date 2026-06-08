# SloSli artifact — field guide

```yaml
kind: SloSli
spec:
  objectives:
    - sli: latency | availability | error-rate   # what is measured
      target: 99.9                                # objective (judgment; needs-review when inferred)
      window: 30d                                 # rolling window the target holds over
      percentile: p99                             # latency only — which percentile the threshold gates
      thresholdMs: 800                            # latency only — "good" is faster than this
      errorBudgetPct: 0.1                         # 100 - target, for convenience
  source: catalog | inferred                      # catalog = authoritative (sre-slo.yml); inferred = drafted
  forFlow: <Flow name>                            # the flow this objective covers
```

**The two sources are not interchangeable**

- `source: catalog` — the objective came from the human-owned `sre-slo.yml`. The engine ingests it
  Tier-A (`common.slo_catalog`) and renders a multi-window **error-budget burn-rate** alert.
- `source: inferred` — you drafted it. It stays `needs-review`; the flow keeps a threshold alert
  marked `needs-review` until a human promotes the target into `sre-slo.yml`. An inferred objective
  **never** feeds a burn-rate alert or the severity floor.

**What good looks like (inferred draft)**

- Exactly one objective per SLI; `sli` is grounded in the cited endpoint/flow that produces it.
- `availability` for any endpoint (target a defensible default like 99.9% / 30d).
- `latency` only when the flow is user-facing/synchronous; tie `thresholdMs` to an **observed**
  timeout or budget in the code, not a round guess — if you can't, omit `thresholdMs` and leave the
  number for the human.
- `forFlow` matches a real `Flow`; `crossRefs` link the `SloSli` to that `Flow`.
- `status: needs-review`, `source: inferred`, confidence lowered to reflect a judgment call.
