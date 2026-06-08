# PRR checks — what each one means and what backs it

`ReadinessScore.spec.prrChecks` is computed deterministically from the scanned facts. Each
check is a boolean; the score is `passed / total`, graded A (≥0.9) → F (<0.4). Use this
table to explain a failing check and locate its fix — never to flip the boolean by hand.

| Check | True when… | Backing fact / kind | Typical fix when false |
|---|---|---|---|
| `healthcheck` | PCF `manifest.yml` declares a health-check type | `pcf.app.healthCheck.type` | Add `health-check-type: http` + endpoint |
| `structured-logging` | structured logging is configured | `observability.logging` | Add JSON/encoder logging (logback/Serilog) |
| `metrics-exposed` | an actuator/metrics endpoint is exposed | `config.actuator` | Enable Actuator / Micrometer metrics |
| `tracing-enabled` | distributed tracing detected | (Sleuth/OTel) | Add OTel/Sleuth — usually fast-follow |
| `timeout-on-egress` | egress calls have a time limit | `config.timelimiter` / `config.client` | Set a client/`@TimeLimiter` timeout |
| `circuit-breaker-on-egress` | a breaker guards egress | `resiliency.circuitbreaker` | Add `@CircuitBreaker` on the egress call |
| `fallback-defined` | a fallback path exists | `resiliency.fallback` | Define a degraded fallback method |
| `slo-target-defined` | an SLO objective is declared | `slo.objective` | Define the SLO (human decision) |
| `burn-rate-alert` | a burn-rate `Alert` exists | `Alert.alertType == burn-rate` | Define the SLO, then the alert follows |
| `alert-for-top-flow` | the top flow has an `Alert` | `Alert` kind present | Generate the alert from the flow |
| `runbook-for-top-flow` | the top flow has a `Runbook` | `Runbook` kind present | Write the runbook for the alert |

## Reading `coverage` and `gaps`

- `coverage.flows` / `flowsWithAlerts` — alert coverage of the discovered request flows.
- `coverage.needsReview` — artifacts the engine couldn't auto-verify; a high count means the
  grade rests on unconfirmed claims, so caveat the verdict.
- `spec.gaps` — human-readable gap strings (SLO missing, no tracing, swallowed failure).
  These are the seed for your remediation plan; expand each into risk + fix + priority.

## Launch-blocking vs. fast-follow

Blocking: `slo-target-defined` false, any flow step with `dataLossRisk`, a `BlastRadius`
with `dependencyCriticality: critical` and no `containment`, `runbook-for-top-flow` false.
Fast-follow: `tracing-enabled`, `structured-logging`, `metrics-exposed` — unless their
absence would make a real incident undiagnosable.
