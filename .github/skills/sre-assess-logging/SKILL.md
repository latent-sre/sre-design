---
name: sre-assess-logging
description: >-
  Tier-B (LLM) logging-quality gap-finder (HYBRID-PLAN S2). The engine already parses the log
  statements deterministically (framework, level distribution, message parameterization, request/
  trace-ID correlation context). You judge what it cannot prove: is an ERROR actually noise
  (alert fatigue), and does a failure site lack request/trace context? Point at verbatim log lines;
  the engine refutes `missing-log-context` against its own correlation facts and routes survivors to
  review. Nothing auto-verifies.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# sre-assess-logging

The **prompt half** of the S2 logging-quality assessment. The engine's `java_spring.log_statements`
collector does the deterministic half — it parses every log statement (level, parameterization) and
the logback correlation pattern, and emits the `Observability.logging` `statements` + `quality`
blocks. You add only the **judgment** the engine can't byte-prove.

## Scope — do NOT re-report what the engine already proves

The engine hands you the context pack plus the logging it already parsed (`observability.logging`:
the format, the `correlationFields` from `%X{}`, per-level counts, parameterized ratio, and any
deterministic `alertFatigueSignals`). Do **not** restate those. Two judgment categories only:

- **`noisy-error-logging`** — an `ERROR`/`WARN` logged for a *routine, non-exceptional* condition
  (a validation miss, an expected 404, a retry that will succeed), or error logging inside a hot
  loop. This is the alert-fatigue call the engine can't make — it sees the level, not the intent.
- **`missing-log-context`** — a failure/catch site whose log line carries **no** request/trace/order
  identifier, so an on-call engineer can't correlate it. (If the service's logback pattern already
  injects `%X{traceId}`, the engine will refute this — only raise it where the context is genuinely
  absent at the call site.)

This is **distinct from** `sre-observability-coverage`'s `missing-structured-logging`, which is the
*pillar-level* present/absent call. Here the structured-logging pillar exists; you assess its
*quality*.

## The non-circular contract (same as sre-gap-finder)

You **point**, the engine **judges**:

1. For each issue, emit a gap whose `anchor` is a **verbatim excerpt** of the offending log
   statement — copied exactly from one UNTRUSTED block. Never a line number.
2. The **engine** locates those bytes and stamps `path:line:excerptHash` with `source_tier: llm`.
   An anchor it can't find verbatim is dropped.
3. The **engine refutes** `missing-log-context` against its own `observability.logging` facts: if
   the format is JSON or carries any `%X{}` correlation field, the gap is dropped (the context is
   global). `noisy-error-logging` is pure judgment — it routes to review, it never auto-verifies.

## Emit

A JSON object written to `.sre/gap-proposals.json` (same file/loader as sre-gap-finder):

```json
{"proposals": [
  {"category": "noisy-error-logging", "target": "payment-service", "severity": "medium",
   "anchor": "log.error(\"invalid amount for account \" + account);",
   "rationale": "ERROR for a routine validation miss — pages on expected input, alert-fatigue risk"},
  {"category": "missing-log-context", "target": "payment-service", "severity": "low",
   "anchor": "log.warn(\"charge retry for account={}\", account, e);",
   "rationale": "retry warning carries no request/trace id to correlate the incident"}
]}
```

`category` ∈ {`noisy-error-logging`, `missing-log-context`}. Every surviving gap is Tier-B
`needs-review` — you widen recall on logging quality; the engine makes the call.
