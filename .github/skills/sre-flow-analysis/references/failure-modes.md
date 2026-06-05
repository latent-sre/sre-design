# Failure-mode catalog (what to look for per step kind)

| Step kind | Common failure modes | Typical `surfacedAs` | Mitigations to check |
|---|---|---|---|
| http-egress | timeout, circuit-open, connection-refused, 5xx | http-503 / http-502 | `@CircuitBreaker`, `@TimeLimiter`, retry+backoff, fallback |
| db-write | db-unavailable, constraint-violation, deadlock | http-500 | tx boundaries, connection-pool limits, idempotency |
| db-read | db-unavailable, timeout | http-500 / degraded | read replicas, cache, timeout |
| message-egress | broker-unavailable, serialization-error | propagated **or** logged-and-swallowed | outbox, transactional publish, retry |
| scheduled | overlap, partial-failure, non-idempotent replay | logged | dedupe key, idempotency, lock |

**Red flags (raise to an Alert / Runbook):**

- A `catch` that logs and does **not** rethrow around a publish/write ⇒
  `logged-and-swallowed` + `dataLossRisk: true`.
- A downstream timeout larger than the flow's latency SLO budget (timeout-vs-SLO).
- An egress with no breaker/timeout and no fallback on a high-SLO flow ⇒ critical
  dependency in `BlastRadius`.
