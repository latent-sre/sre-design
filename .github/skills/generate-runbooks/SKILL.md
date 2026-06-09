---
name: generate-runbooks
description: >-
  Generate-phase (Tier-B) runbook drafter (coverage #20) — author the diagnosis/remediation content
  for an Alert that has no runbook. The engine already writes the one runbook it can fully derive (a
  swallowed-publish failure); you draft the rest, grounded in the scanned flows and dependencies. Each
  runbook triggers on a real Alert and references only real artifacts; the engine re-grounds the target
  and every Kind/name citation against the run, flagging anything that isn't there. Use when asked to
  draft a runbook, write incident steps, or document what to do when an alert fires. Nothing you draft
  auto-verifies — it lands needs-review with a GENERATED banner.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# generate-runbooks

The **prompt half** of the coverage #20 runbook drafter. The engine scaffolds a Runbook only for a
swallowed-publish Alert — the one failure mode it can fully derive. Every other Alert (a burn-rate
alert, for instance) ships with **no** runbook. You author the diagnosis/remediation content the
engine can't, grounded in the flows, dependencies, and resiliency facts it already extracted.

## Scope — draft for an uncovered Alert, ground every reference

The engine hands you the context pack plus its scaffolded artifacts. For each `Alert` that has **no**
`Runbook`, draft one:

- **symptoms** — what an on-call sees when this alert fires.
- **diagnosis** — ordered checks, referencing the real `Flow`/`Dependency`/`ResiliencyPattern`
  artifacts the alert touches (cite them as `Kind/name`).
- **remediation** — the concrete steps to mitigate.
- **escalation** — who owns it.

Do **not** invent a flow, dependency, or service that the scan didn't produce — the engine grounds
every `Kind/name` reference against this run and flags anything that isn't there. Do **not** draft a
second runbook for an Alert that already has one (the engine refuses duplicates).

## The non-circular contract

You **draft**, the engine **grounds**:

1. Emit one runbook per uncovered Alert, its `alertRef` set to that **real** Alert's name. An
   `alertRef` that resolves to no Alert in the run is dropped; an Alert that already has a runbook is
   refused.
2. The **engine** grounds every `Kind/name` reference in your prose against the run's artifacts; an
   ungrounded reference (a flow/dependency that isn't there) is named so it can't hide in a step.
3. Survivors are Tier-B `needs-review` `Runbook` artifacts with the GENERATED banner, byte-grounded to
   the same code their target Alert cites. You authored the content; the engine made every grounding
   call.

## Emit

A JSON object written to `.sre/runbook-proposals.json`:

```json
{"proposals": [
  {"alertRef": "create-order-latency-burn-rate", "relatedFlow": "create-order",
   "symptoms": ["p99 latency on the create-order route is burning the error budget"],
   "diagnosis": ["Check the publish path in Flow/create-order for backpressure",
                 "Inspect downstream dependency latency for the order-kafka binding"],
   "remediation": ["Shed load or scale the slow dependency",
                   "Confirm the burn is sustained, not a transient spike"],
   "escalation": "orders on-call"}
]}
```

`alertRef` is required and must be a real Alert. Every surviving proposal is Tier-B `needs-review`.
The engine runs `sre-kb generate-runbooks` to re-ground them.
