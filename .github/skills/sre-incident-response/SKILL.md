---
name: sre-incident-response
description: 'On-call companion: given a symptom, a firing alert, or a failing dependency, find the relevant flow, blast radius, and runbook in an already-published SRE knowledge base and walk the responder through a grounded response. Use during an incident, when an alert fires, when a dependency is down, or to ask what to do about a symptom for a service. CONSUMER side — reads a published KB, does not scan code. Keywords: incident, on-call, alert firing, runbook, what do I do, dependency down, outage, paged, mitigate, escalate.'
---

# SRE incident response (consumer skill)

This is the **consumer** half of the SRE KB. The authoring skills (`sre-flow-analysis`,
`sre-prr-review`, `sre-blast-radius`, `sre-estate`) *build* the knowledge base from code.
This skill *uses* an already-published KB to help an on-call engineer respond to an
incident — fast, and grounded in what the KB actually says. It does **not** run the scanner
or invent procedure; it routes the responder to the validated artifacts.

## When to use this skill

- "Alert `X` is firing — what do I do?"
- "`inventory-service` / `orders-postgres` is down — what's the impact and the runbook?"
- "We're seeing `<log line / symptom>` in `<service>` — walk me through it."

## Where the KB lives

A published KB sits in the SRE/Backstage repo under `catalog/<service>/` (see
[references/kb-layout.md](./references/kb-layout.md)):

```
catalog/<service>/
  kb/verified/<Kind>/*.yaml     Flow, Alert, Runbook, BlastRadius, ...
  runbooks/*.md                 rendered, human-readable runbooks
  FINDINGS.md                   ranked known risks
  diagrams/*.mmd                sequence + topology
```

Use [scripts/lookup.sh](./scripts/lookup.sh) `<catalog-dir> <term>` to grep the tree for an
alert name, dependency, log string, or endpoint and list the artifacts that mention it.

## Workflow (during an incident)

1. **Identify the entry point.** Match the symptom to an artifact:
   - an alert name / detection string → the `Alert`;
   - a failing dependency or datastore → its `BlastRadius`;
   - an endpoint / request path → the `Flow`.
   `lookup.sh` is the fast path.
2. **Assess impact** from the `BlastRadius` / `FINDINGS.md`: which flows and services degrade,
   whether there's `dataLossRisk`, and the `severityHint`. State it plainly to the responder.
3. **Go to the runbook.** Follow the `Alert`'s `relatedFlow` / the runbook's `alertRef` to the
   matching `runbooks/<name>.md`. Present Symptoms → Diagnosis → Remediation **in order**.
4. **Respect the banner.** Every generated runbook says *verify before executing*. Treat each
   remediation step as a draft to confirm against current system state — especially anything
   destructive or data-losing. Read out the `Escalation` path if the step is risky or stalls.
5. **Stay grounded.** Answer only from the published KB. Every diagnosis step cites a
   `path:line` into the service; if the KB doesn't cover the symptom, say so and fall back to
   `FINDINGS.md` / escalation — do **not** invent steps. See
   [references/provenance-rules.md](./references/provenance-rules.md).

## Safety rules (non-negotiable during an incident)

- **Never invent a remediation step.** If it isn't in the runbook, it isn't a step. Surface
  the gap and escalate instead.
- **Flag destructive actions.** Call out any step that deletes/overwrites/replays data and
  require explicit confirmation before recommending it.
- **The KB can be stale.** It's validated against a commit, not live state. Treat it as the
  best-known starting point, verify against telemetry, and prefer escalation over a guess.
- **`needs-review` artifacts are drafts.** If the only relevant artifact is under
  `kb/needs-review/`, say it's unconfirmed and lean on human judgment.
