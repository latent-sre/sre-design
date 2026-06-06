# sre-design — SRE Knowledge-Base Generator (`sre-kb`)

A repo-neutral engine that performs a deep SRE review of a target code repository and
emits a **populated, validated SRE knowledge base** as schema-tagged YAML (`apiVersion`
+ `kind`), then projects it into **GitHub Copilot** skills/agents and opens a PR into a
company SRE repo.

Two halves:

- **Python engine (`sre_kb`)** — the *deterministic* half: scans a locally-cloned repo,
  extracts facts with hard provenance (`path:line` + commit + `excerptHash`), scaffolds
  artifacts, **validates** them (schema + provenance + cross-ref + gating), renders
  projections, and publishes.
- **GitHub Copilot in VS Code** — the *LLM* half (the only approved LLM): its agent mode
  enriches the scaffolded artifacts, driven by the Agent Skills / custom agent / prompt
  files this repo ships. The engine **never calls an LLM**.

The full design lives in [`docs/DESIGN.md`](docs/DESIGN.md).

## Status

Working engine — P1 vertical slice, P2 breadth, and P3 security hardening implemented
and tested offline against the bundled fixtures. See `docs/DESIGN.md` for the full design.

Implemented:
- **Scan → scaffold → validate** (4 layers: schema, provenance hash, cross-ref, gating)
  for ~22 kinds incl. Flow, Alert (log-pattern + SLO burn-rate), Runbook, BlastRadius,
  ResiliencyPattern, Observability, SloSli, ReadinessScore (PRR grade), TechStack,
  Architecture, Deployment, Dependency, Interface, DataStore, ConfigManagement.
- **Render**: Mermaid sequence + topology diagrams, Copilot reliability guardrails, runbooks.
- **Publish** (`--dry-run`): Backstage per-service PR tree + REVIEW.md; SCM-neutral Forge.
- **Drift** (`sre-kb diff`) and **Estate** (`sre-kb estate`: cross-service topology + co-tenancy).
- **Security**: publish-time secret-scan gate, dangerous-pattern output lint, untrusted-input
  context packs, engine resource limits.
- Shipped Copilot driver under `.github/` (sre-analyst agent + sre-flow-analysis skill).

## Quickstart (dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                                   # the test suite
sre-kb schema list                                          # the kind registry
sre-kb run --target tests/fixtures/sample-spring-pcf --to-stage publish
sre-kb estate --target tests/fixtures/sample-spring-pcf --target tests/fixtures/sample-billing-pcf
```
