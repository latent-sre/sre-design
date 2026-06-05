# Flow artifact — field guide

```yaml
kind: Flow
spec:
  trigger: { type: http|message|scheduled, method?, path?, entrypoint }
  steps:
    - id: s1
      name: <verb-noun>            # e.g. call-reserve, persist, publish-order-created
      kind: http-egress | db-write | db-read | message-egress | internal
      failureModes:
        - mode: timeout | circuit-open | db-unavailable | broker-unavailable | validation-error
          surfacedAs: http-4xx | http-5xx | logged-and-swallowed | propagated
          dataLossRisk: true        # set when a write/publish failure is swallowed
  sinks: [ { type, target } ]
  sloRef: <SloSli name>             # if an SLO exists for this flow
```

**What good looks like**

- Steps are ordered by call site (source line order).
- Each egress step has at least one failure mode and, where present, a `ResiliencyPattern`
  / `Fallback` cross-ref.
- A swallowed publish/write keeps `surfacedAs: logged-and-swallowed` + `dataLossRisk: true`
  — this is the seed for the Alert and the data-loss `BlastRadius`.
- `crossRefs` link the Flow to its `ResiliencyPattern`, `Fallback`, and `Alert`.
