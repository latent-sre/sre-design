---
name: sre-generate-slos
description: >-
  Generate-phase (Tier-B) SLO drafter — propose candidate SLI definitions and objectives for a
  service's endpoints and critical flows that have no authoritative SLO, grounded in the cited
  endpoint/flow code. Use when asked to draft SLOs/SLIs, suggest reliability targets, or fill the SLO
  coverage gap for a scanned service. Every proposal lands needs-review with source=inferred: a drafted
  target is a judgment, never authoritative, and never feeds the burn-rate alert or severity floor.
  Keywords: SLO, SLI, objective, error budget, reliability target, latency, availability, burn rate.
allowed-tools: ["codebase", "search", "editFiles", "runCommands"]
metadata:
  version: 0.1.0
---

# sre-generate-slos

Draft **candidate** SLOs for a scanned service — one SLI + objective per endpoint or critical
flow that has no SLO yet — grounded in the real code. This is the first `generate`-phase skill
(DEEP-COMPARISON R7); it widens SLO *coverage*, it does not set targets.

## When to use this skill

- "Draft SLOs / SLIs for this service."
- "Which endpoints have no reliability target?"
- After `sre-flow-analysis` has produced Flows, and the service ships **no** `sre-slo.yml`.

## Prerequisites

- A scaffolded run exists (`sre-kb run --target <repo> --to-stage scaffold`); the engine has
  emitted `Flow` and (minimal) `SloSli` candidates under `.work/<run>/candidates/`.

## The trust boundary (read this first)

An SLO target is a **judgment call**. The engine treats a drafted target very differently from an
authoritative one, and you must not blur the two:

1. **Authoritative SLOs live in `sre-slo.yml`** (human-owned). When that file is present the engine
   ingests it Tier-A (`source: catalog`), and a flow gets a real error-budget **burn-rate** alert.
   **Never create or edit `sre-slo.yml`** — you cannot promote a guess to authoritative.
2. **You draft into the scaffolded `SloSli` candidate** with `source: inferred` and
   `status: needs-review`. An inferred SLO never feeds the burn-rate alert or the severity floor —
   the flow keeps its `needs-review` threshold alert until a human ratifies the target. That gating
   is the engine's, not yours; your job is to give the human a code-grounded starting point.
3. **You point at the SLI, you don't certify the number.** Cite the endpoint/flow the SLI measures
   (`path:line` in context). The `sli` is grounded in code that exists; the `target`/`window` are
   proposals a human accepts or overrides.

## Workflow

1. For each `Flow` (and each endpoint without a `sloRef`), pick the natural SLI:
   `availability` for any endpoint, `latency` for a user-facing or synchronous flow. Read
   [references/slo-fields.md](./references/slo-fields.md) for the field meanings.
2. Write the proposal into the flow's `SloSli` candidate: one objective per SLI, `source: inferred`,
   `forFlow: <flow name>`, `status: needs-review`. Cite the endpoint handler the SLI measures.
   Leave `target`/`window` as your best **defensible** draft (e.g. `availability` 99.9% / 30d,
   `latency` p99 with a threshold tied to an *observed* timeout in the code) — never a number you
   cannot motivate from the facts.
3. Obey [references/provenance-rules.md](./references/provenance-rules.md): cite only `path:line`
   present in context; never invent endpoints, metrics, or thresholds.
4. Run `sre-kb run --target <repo> --run <id> --to-stage validate` and fix flagged items until each
   `SloSli` is a clean `needs-review` (drafted) or `verified` (only if it merely echoes an
   authoritative catalog).

## Gotchas

- **`source: inferred`, always.** `source: catalog` means "a human declared this in `sre-slo.yml`".
  Marking a draft `catalog` would let the engine build a burn-rate alert on a guessed target — the
  exact failure this boundary prevents.
- **Tie latency thresholds to evidence.** If the code sets a 2s client timeout, a p99 latency
  threshold near it is defensible; a round number with no anchor is not — drop the threshold and
  let the human set it rather than invent one.
- **One SLI per concern.** Don't stack availability + latency + saturation into one objective; emit
  separate objectives so a human can accept or reject each independently.
- **No flow, no SLO.** Don't draft an SLO for an endpoint you can't tie to a `Flow` — that's a
  coverage gap to report, not a target to invent.
- The model is unset on purpose (LLM-neutral) — this skill works under any Copilot model.
