---
name: map-messaging
description: >-
  Tier-B (LLM) consumer-side messaging-resilience gap-finder (HYBRID-PLAN S3). The engine already
  detects each consumer's dead-letter route, retry, and idempotency guard deterministically (the
  Messaging kind). You judge what it cannot prove: ordering/partition safety, whether a poison pill
  is genuinely handled, and saga/distributed-transaction compensation. Point at verbatim handler
  code; the engine refutes missing-poison-pill-handling against its own consumer facts and routes
  survivors to review. Nothing auto-verifies.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# map-messaging

The **prompt half** of the S3 consumer-side messaging assessment. The engine's
`java_spring.messaging` collector does the deterministic half — it detects every
`@KafkaListener`/`@RabbitListener`/`@SqsListener`/`@JmsListener`, its DLQ mechanism
(`@RetryableTopic`/`@DltHandler`/binder config), retry, and idempotency guard, and emits both the
`Messaging` artifact and the Tier-A `consumer-without-dlq` / `non-idempotent-consumer` gaps. You add
only the **judgment** the engine can't byte-prove.

## Scope — do NOT re-report what the engine already proves

The engine hands you the context pack plus the consumers it already mapped. Do **not** restate DLQ or
idempotency *presence/absence* — those are deterministic. Three judgment categories only:

- **`unordered-consumer`** — ordering/partition safety: a handler that assumes per-key ordering but
  runs with concurrency, or processes a partitioned topic in a way that reorders effects.
- **`missing-poison-pill-handling`** — a bad/unparseable message that the handler can neither process
  nor route off the partition. (If the consumer has a dead-letter route, the engine refutes this —
  raise it only where a malformed message would actually block or crash-loop the partition.)
- **`missing-saga-compensation`** — a multi-step distributed transaction with no compensating action
  on partial failure. **Permanently Tier-B**: there is no deterministic ground truth for "this needed
  a saga." Always routes to review.

## The non-circular contract (same as sre-gap-finder)

You **point**, the engine **judges**:

1. For each issue, emit a gap whose `anchor` is a **verbatim excerpt** of the handler code — copied
   exactly from one UNTRUSTED block. Never a line number.
2. The **engine** locates those bytes and stamps `path:line:excerptHash` with `source_tier: llm`.
   An anchor it can't find verbatim is dropped.
3. The **engine refutes** `missing-poison-pill-handling` against its own `message.consumer` facts (a
   dead-letter route already handles it). `unordered-consumer` and `missing-saga-compensation` are
   judgment — they route to review, never auto-verify.

## Emit

A JSON object written to `.sre/gap-proposals.json` (same file/loader as sre-gap-finder):

```json
{"proposals": [
  {"category": "unordered-consumer", "target": "order.shipped", "severity": "medium",
   "anchor": "@KafkaListener(topics = \"order.shipped\", groupId = \"orders\")",
   "rationale": "stateful update keyed by order, but the listener runs concurrently — effects can reorder"},
  {"category": "missing-saga-compensation", "target": "order.created", "severity": "high",
   "anchor": "processed.save(event.idempotencyKey());",
   "rationale": "reserve-then-charge across services with no compensating release on charge failure"}
]}
```

`category` ∈ {`unordered-consumer`, `missing-poison-pill-handling`, `missing-saga-compensation`}.
Every surviving gap is Tier-B `needs-review` — you widen recall on messaging judgment; the engine
makes the deterministic calls.
