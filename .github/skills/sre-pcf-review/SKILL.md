---
name: sre-pcf-review
description: >-
  Assess-phase (Tier-B) PCF deployment reviewer (§3.2) — judge which manifest settings deserve
  operator attention: a single-instance app with no failover, a port health check on an HTTP
  service, a missing disk quota, endpoint-shaped env config that belongs in a service binding.
  The engine collects every manifest fact; you add the judgment it can't make (one instance can
  be correct for a worker, a port check can be right for a TCP process). Propose check+app pairs;
  the engine re-derives every accepted check from the manifest bytes and refutes what they
  disprove. Use when asked to review a PCF deployment, manifest, or platform posture. Nothing you
  propose auto-verifies.
allowed-tools: ["codebase", "search", "editFiles"]
metadata:
  version: 0.1.0
---

# sre-pcf-review

The **prompt half** of the §3.2 PCF deployment review. The engine's `common.manifest_pcf` collector
parses every `manifest*.yml` (instances, processes, sidecars, routes, health checks, disk, env, with
per-environment `((var))` interpolation). What it can't decide is **whether a setting is a problem
for this app** — that's the judgment you add.

## The check vocabulary (closed — anything else is dropped)

| check | the judgment you're making |
|---|---|
| `single-instance` | the app (or its sole web process) runs one instance **and that matters** — an HTTP app with no failover, not a batch worker |
| `port-health-check` | `health-check-type` is `port`/unset while the app serves HTTP routes — the platform can't see application health |
| `missing-disk-quota` | no `disk_quota` declared, for an app where disk pressure is plausible |
| `env-config-binding` | an env var carries endpoint-shaped config (a URL/URI/host) that belongs in a service binding |

## The non-circular contract

You **point**, the engine **judges**:

1. Read the run's manifest facts (`facts/facts.jsonl`, `pcf.app` entries) or the manifests directly.
2. Propose only the (check, app) pairs that genuinely deserve attention — most don't; that
   restraint is the whole value of the task.
3. The **engine** (`sre-kb pcf-review --target <repo>`) re-derives every accepted check from the
   manifest bytes: a `single-instance` claim on a 3-instance app is refuted regardless of your
   rationale. Survivors land as advisory findings (`source: llm`) in `.sre/pcf-review.json` —
   never verified artifacts.

## Emit

A JSON object written to `.sre/pcf-review-proposals.json`:

```json
{"proposals": [
  {"check": "single-instance", "app": "order-service", "severity": "high",
   "rationale": "an HTTP app on the critical order path with one instance has no failover"},
  {"check": "env-config-binding", "app": "order-service", "severity": "medium",
   "rationale": "INVENTORY_API_URL in env duplicates what a service binding should declare"}
]}
```

Reply `{"proposals": []}` when nothing deserves attention. The engine runs `sre-kb pcf-review`
to re-ground them.
