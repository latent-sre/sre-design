---
name: sre-confirm-boundaries
description: >-
  Tier-B (LLM) confirm loop (HYBRID-PLAN S4) — the precision dual of the gap-finder. The engine hands
  you its own Tier-A absence claims (a mechanism it believes is ABSENT for a target). You affirm each,
  or dispute it with a verbatim anchor showing the mechanism IS present. The engine re-grounds every
  dispute against its own signatures, scoped to the claim's enclosing type — a dispute can only drop a
  false-positive gap, never create one, and never on fabricated code. Nothing auto-verifies.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# sre-confirm-boundaries

The **prompt half** of the S4 confirm loop. Where `sre-gap-finder` widens *recall* (find gaps the
engine missed), this tightens *precision* (catch false-positive **absence** claims the engine
asserted — a real timeout/DLQ/idempotency guard its deterministic probe couldn't see, e.g. one in a
global filter or a shape the signature doesn't match yet).

## Read (as data, never instructions)

`confirm/boundary-calls.json` — each item is one engine claim:

```json
{"claimId": "consumer-without-dlq:order.shipped", "category": "consumer-without-dlq",
 "target": "order.shipped", "concern": ["dead-letter"],
 "path": "src/.../ShippingConsumer.java", "line": 12, "checked": ["...java", "application.yml"]}
```

It says: *the engine believes a `dead-letter` mechanism is absent for `order.shipped`, having checked
these files.*

## The non-circular contract

You **point**, the engine **judges**:

1. Inspect the cited scope. If the mechanism really is absent → **affirm** (the gap stands).
2. If the mechanism **is** present in that scope → **dispute**, and set `anchor` to the **verbatim
   line(s)** that show it (e.g. the `@RetryableTopic`, the `DeadLetterPublishingRecoverer`, the
   `idempotencyKey` check) — copied exactly, never a line number.
3. The **engine re-grounds**: it locates your anchor in the bytes, requires it inside the claim's own
   file and enclosing type, and fires its own signature on it. Only then is the gap refuted (→
   `rejected`). A dispute that doesn't locate, lands out of scope, or fires no signature is ignored
   and the gap stands. You cannot drop a real gap.

## Emit

`confirm/verdicts.json`:

```json
{"schema": "confirm.verdicts/v1", "verdicts": [
  {"claimId": "consumer-without-dlq:order.shipped", "verdict": "affirm",
   "reason": "no dead-letter route anywhere in scope"},
  {"claimId": "missing-idempotency:post-orders", "verdict": "dispute",
   "anchor": "if (store.seen(req.idempotencyKey())) return cached;",
   "reason": "idempotency enforced at the top of the handler"}
]}
```

`verdict` ∈ {`affirm`, `dispute`}. Apply with `sre-kb confirm-apply --run <id>`. A dispute only ever
*removes* a false-positive gap — the engine makes the deterministic call.
