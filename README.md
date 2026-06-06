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

Working engine, tested offline (128 tests, ruff-clean) against bundled **Java/Spring**,
**.NET/Steeltoe**, and multi-endpoint fixtures — the same collectors emit the same KB for
both languages (repo-neutrality). See [`docs/DESIGN.md`](docs/DESIGN.md) for the full
design and a current implementation-status section.

Implemented:
- **AST-backed extraction** — code structure (classes, methods, calls, annotations,
  try/catch) is read from a tree-sitter model (Java + C#, `parsing/code_model.py`) with
  per-class scoping and receiver→field-type call correlation; only config files use
  direct parsing. Confidence is signal-derived; BlastRadius risk is computed from breadth.
- **Trust tiers (provenance)** — every evidence item carries a `source_tier` (`ast`
  deterministic | `llm`), rolled up per artifact in the validation report. The foundation for
  fenced LLM (Tier-B) collectors that can only add `needs-review` candidates, never auto-verify.
- **Scan → scaffold → validate** (5 layers: schema, provenance hash, cross-ref, gating,
  and an adversarial challenge pass that grounds each claim against its cited evidence)
  for ~22 kinds incl. Flow, Alert (log-pattern + SLO burn-rate), Runbook, BlastRadius,
  ResiliencyPattern, Observability, SloSli, ReadinessScore (PRR grade), TechStack,
  Architecture, Deployment, Dependency, Interface, DataStore, ConfigManagement.
- **Render**: Mermaid sequence + topology diagrams, Copilot reliability guardrails, runbooks.
- **Publish**: Backstage per-service PR tree + REVIEW.md + FINDINGS.md; SCM-neutral Forge.
  `--dry-run` stages locally; `--no-dry-run` opens a live PR via git + GitHub REST (`GITHUB_TOKEN`).
- **Findings** (`sre-kb findings`) — ranked, evidence-linked risk digest (CI-gateable).
- **Drift** (`sre-kb diff`) and **Estate** (`sre-kb estate`: cross-service topology + co-tenancy).
- **Security**: redact + publish-time secret-scan gate (defense-in-depth), non-escapable
  untrusted-input context packs, sanitized renderers, publish-repo allowlist with the token
  kept out of `git` argv, fan-out cap, dangerous-pattern output lint, engine resource limits.
- **Copilot driver** under `.github/` (sre-analyst agent + sre-flow-analysis skill) with the
  challenge loop: the engine emits a worklist, Copilot adjudicates, `sre-kb challenge-apply`
  re-gates the verdicts (monotonic, downgrade-only).

## What's next

The roadmap is [`docs/HYBRID-PLAN.md`](docs/HYBRID-PLAN.md); §8 tracks status. Phase 0 (trust
tiers) and Phase 1 (output + publish hardening) have landed. Next, in order:

- **Status-aware trust spine** — cross-ref / readiness / gating require *verified* referents and
  confine provenance paths, so Tier-B facts can't inflate a "verified" graph (Phase 2).
- **Schema governance** — `additionalProperties: false` per kind, an `ownership` field, and a
  golden-example-per-kind corpus in CI (§7.6).
- **Fenced LLM (Tier-B) collectors** — a gap-finder that proposes pointers the engine
  re-derives or refutes; anything it proposes lands `needs-review`, never auto-verified
  (Phase 3–4, §7.9). This is also how new stacks (Node, Python) gain breadth.
- **Render-adapter breadth** — AppDynamics / Wavefront emitters beyond Splunk + Prometheus (Phase 5).

Known limitations (documented, not bugs): variable-topic egress (non-literal Kafka topics)
and cross-file call-graph beyond a single handler body are out of scope for the per-file
AST model.

## Quickstart (dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                                   # the test suite (128 tests)
sre-kb schema list                                          # the kind registry

# scan -> scaffold -> validate -> render -> stage a PR tree (dry-run)
sre-kb run --target tests/fixtures/sample-spring-pcf --run demo --to-stage publish
sre-kb findings --run demo                                  # ranked risk digest

# repo-neutrality: the same engine on a .NET/Steeltoe service
sre-kb run --target tests/fixtures/sample-dotnet-steeltoe --run net --to-stage validate

# cross-service co-tenancy blast radius
sre-kb estate --target tests/fixtures/sample-spring-pcf --target tests/fixtures/sample-billing-pcf
```
