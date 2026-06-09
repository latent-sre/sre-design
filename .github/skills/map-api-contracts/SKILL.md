---
name: map-api-contracts
description: >-
  Tier-B (LLM) API-contract versioning gap-finder (coverage #7). The engine already diffs the current
  OpenAPI spec against the committed `.sre/api-baseline/` baseline and deterministically classifies
  the structural breaking changes — operation removed/added, a newly-required request parameter — and
  the semver version-policy. You judge only what the shape diff cannot prove: a SEMANTIC break, where
  an operation keeps the same shape but changes meaning (units, default, enum semantics, an auth or
  status-code contract). Point at verbatim spec text from both versions; the engine re-grounds each
  against its own diff (dropping anything that merely restates a structural change) and routes genuine
  semantic breaks to review. Nothing auto-verifies.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# map-api-contracts

The **prompt half** of the coverage #7 versioning assessment. The engine's `common.openapi` collector
does the deterministic half — given a baseline spec under `.sre/api-baseline/`, it emits every
`operation-removed` (breaking), `operation-added` (non-breaking), and `required-parameter-added`
(breaking) change, byte-grounded to the spec line, plus a `versionPolicy` that fails when a breaking
change ships without a major bump. You add only the **judgment** the engine can't byte-prove.

## Scope — do NOT re-report what the engine already proves

The engine hands you the context pack plus the changes it already classified (the `Interface`
artifact's `contract.changes` and `contract.versionPolicy`). Do **not** restate a removed/added
operation, a newly-required parameter, or the version bump — those are deterministic. One judgment
category only:

- **`semantic-break`** — an operation present in **both** the baseline and the current spec, with the
  **same** method/path/parameter shape, whose **meaning** changed in a way that breaks an existing
  client: a field's units or type-as-documented (a string that was an ISO date now an epoch int), a
  default value change, an enum value removed or repurposed, a response status-code contract change, a
  newly-required authentication scheme, or a pagination/ordering guarantee dropped. There is no
  deterministic ground truth for "this meaning changed in a breaking way" — it always routes to review.

## The non-circular contract (same as sre-gap-finder)

You **point**, the engine **judges**:

1. For each issue, emit a proposal whose `anchor` is a **verbatim excerpt** of the *current* spec —
   copied exactly from one UNTRUSTED block (e.g. the changed field or enum). Never a line number.
   Put the baseline meaning in `was` and the new meaning in `rationale`.
2. The **engine** locates those bytes and stamps `path:line:excerptHash` with `source_tier: llm`.
   An anchor it can't find verbatim in the current spec is dropped.
3. The **engine refutes** any proposal whose operation the deterministic diff already flags as a
   *structural* change (removed/added/newly-required) — that is not a semantic break, it is already
   covered. Survivors are Tier-B `needs-review`; you widen recall on semantic versioning judgment, the
   engine makes the deterministic calls.

## Emit

A JSON object written to `.sre/contract-proposals.json`:

```json
{"proposals": [
  {"target": "GET /api/v1/orders/{id}", "severity": "high",
   "anchor": "format: epoch-millis",
   "was": "createdAt was an ISO-8601 string (format: date-time)",
   "rationale": "createdAt changed from an ISO-8601 string to epoch milliseconds — existing clients that parse a date string break, though the field name and type are unchanged"},
  {"target": "POST /api/v1/orders", "severity": "medium",
   "anchor": "default: STANDARD",
   "was": "priority defaulted to EXPEDITED",
   "rationale": "the default priority changed, silently altering behaviour for clients that omit the field"}
]}
```

`category` is always `semantic-break` (you may omit it; the engine defaults it). Every surviving
proposal is Tier-B `needs-review`. The engine runs `sre-kb map-contracts` to re-ground them.
