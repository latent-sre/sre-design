# Published KB layout (what the consumer reads)

When `sre-kb publish` opens a PR into the SRE/Backstage repo, each service lands under
`catalog/<service>/`. As a responder you read this tree — you do not run the engine.

```
catalog/<service>/
  catalog-info.yaml          Backstage component entry
  kb/
    verified/<Kind>/*.yaml    auto-verified artifacts (trust these first)
    needs-review/<Kind>/*.yaml unconfirmed drafts (caveat before acting)
  runbooks/<name>.md          rendered runbooks (Symptoms/Diagnosis/Remediation + flow diagram)
  diagrams/*.mmd              Mermaid sequence + topology
  REVIEW.md                   what wasn't auto-verified
  FINDINGS.md                 ranked known risks (data-loss, uncontained critical deps)
```

## How the artifacts link up (follow these refs)

- **Alert → Runbook.** An `Alert` names its failure mode; the `Runbook` references it via
  `spec.trigger.alertRef`. The rendered runbook file is `runbooks/<runbook-name>.md`.
- **Runbook → Flow.** `Runbook.spec.relatedFlow` points at the `Flow`; the runbook markdown
  embeds that flow's sequence diagram.
- **Dependency/Datastore → BlastRadius.** A `BlastRadius` whose `spec.node.name` matches the
  failing dependency tells you `impactedFlows`, `impactedServices`, `containment`, and
  `stateful.dataLossRisk`.
- **Anything → code.** Every artifact's `evidence[]` carries `path:line` into the service repo.
  Quote it so the responder can confirm against the actual code.

## Fast triage order

1. `FINDINGS.md` — is this a *known* risk? If so, the highest-severity finding names the node
   and links the artifact.
2. The `Alert` matching the firing signal → its `Runbook`.
3. The `BlastRadius` for the failing node → impact + whether data is at risk.
4. The `Flow` for end-to-end context + the sequence diagram.
