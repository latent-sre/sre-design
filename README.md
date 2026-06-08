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

Working engine, tested offline (450 tests, ruff-clean) against bundled **Java/Spring**,
**.NET/Steeltoe**, **Python/FastAPI**, and **Node/Express** fixtures — the same collectors emit the
same KB across stacks (repo-neutrality). See [`docs/DESIGN.md`](docs/DESIGN.md) for the full
design and a current implementation-status section.

Implemented:
- **AST-backed extraction** — code structure (classes, methods, calls, annotations,
  try/catch) is read from a tree-sitter model (Java, C#, and Python — `parsing/code_model.py`)
  with per-class scoping and receiver→field-type call correlation; only config files use
  direct parsing. Python/FastAPI emits the same facts (endpoints, egress, tech stack) so the
  unchanged scaffolder produces the same KB; Node/Express adds a `package.json` tech-stack slice
  (framework + runtime + deps) by direct parse — no new dependency. Confidence is signal-derived.
- **Trust tiers (provenance)** — every evidence item carries a `source_tier` (`ast`
  deterministic | `llm`), rolled up per artifact in the validation report. Tier-B proposals stay
  fenced unless the engine independently confirms them with a deterministic rule at the cited bytes.
- **LLM gap-finder (Tier-B, spike)** — Copilot proposes resiliency gaps the AST missed
  (e.g. a client with no timeout); the engine locates each, stamps `path:line:hash`
  (`source_tier=llm`), and re-derives/refutes it via the shared `signatures` library. Refutation
  gaps land `ResiliencyGap` / `needs-review`; confirmation gaps can graduate to Tier-A when the
  deterministic rule fires. The first real-Copilot sample validation measured 4/4 recall and no
  false-positive survivors; service-scale noise remains open.
  `sre-kb gap-finder`; see [`docs/PHASE-4-GAP-FINDER.md`](docs/PHASE-4-GAP-FINDER.md).
- **Scan → scaffold → validate** (5 layers: schema, provenance hash, cross-ref, gating,
  and an adversarial challenge pass that grounds each claim against its cited evidence)
  for ~28 kinds incl. Flow, Alert (log-pattern + SLO burn-rate), Runbook, BlastRadius,
  ResiliencyPattern, Observability, SloSli, ReadinessScore (PRR grade), TechStack, Criticality,
  ScheduledJob, Dashboard, ResiliencyGap, Architecture, Deployment, Dependency, Interface,
  DataStore, ConfigManagement.
- **Render**: Mermaid sequence + topology diagrams, Copilot reliability guardrails, runbooks.
- **Publish**: Backstage per-service PR tree + REVIEW.md + FINDINGS.md; SCM-neutral Forge.
  `--dry-run` stages locally; `--no-dry-run` opens a live PR via git + GitHub REST (`GITHUB_TOKEN`).
- **Findings** (`sre-kb findings`) — ranked, evidence-linked risk digest (CI-gateable).
- **Drift** (`sre-kb diff`) and **Estate** (`sre-kb estate`: cross-service topology + co-tenancy).
- **Security**: fail-closed publish-time secret-scan gate (redaction on the `--allow-secrets`
  override), non-escapable untrusted-input context packs, sanitized renderers, publish-repo
  allowlist with the token kept out of `git` argv, fan-out cap, dangerous-pattern output lint,
  engine resource limits, and a read-only `sre-target-scan` agent for untrusted repos.
- **Copilot driver** under `.github/` split into an **authoring** side (the `sre-analyst` +
  read-only `sre-target-scan` agents, and the `sre-flow-analysis`, `sre-blast-radius`,
  `sre-prr-review`, `sre-estate`, `sre-criticality`, `sre-gap-finder`, `sre-observability-coverage`
  skills that *build* the KB) and a **consumer** side (the `sre-oncall` agent +
  `sre-incident-response` skill that *use* a published KB during an incident).
- **Challenge loop, automatable end-to-end:** the engine emits a worklist, an oracle
  adjudicates, `sre-kb challenge-apply` re-gates (monotonic, downgrade-only). `sre-kb
  challenge-run --oracle '<llm-cli>'` drives the loop through an external LLM CLI on stdin —
  the engine embeds no model; with no oracle it defers to a human, exactly as offline.

## What's next

The roadmap is [`docs/HYBRID-PLAN.md`](docs/HYBRID-PLAN.md); §8 tracks status and §9 the post-spike
reassessment. Phases 0–3 (trust tiers, output + publish hardening, the status-aware trust spine, and
the Copilot challenge loop), the §7.6 schema governance, and the **Phase 4 gap-finder spike** have
landed. Phase 4 now has refutation probes (`missing-timeout`, `unguarded-critical-dependency`),
confirmation probes (`swallowed-failure`, `undocumented-job`), judgment routing, target-scoped config
probing, and a noise budget. The spike cleared the plan's make-or-break bar, and it is now **wired
into `sre-kb run`** (a `.sre/gap-proposals.json` is auto-detected and routed through the shared gate;
§9.3 item 1). The remaining order is **integrate before expand** (§9.3):

- **Graduation loop** — a reviewer records verdicts with `sre-kb confirm-gap`; once a gap category
  recurs (threshold reached, zero false positives) `sre-kb graduation-candidates` drafts the
  deterministic signature to review and merge, ratcheting the engine's recall upward (assisted, never
  auto-applied).
- **Render-adapter breadth** (Phase 5) — a tool-neutral alert-intent → adapter seam emits
  Prometheus, Splunk, Wavefront, AppDynamics, Grafana, and ThousandEyes from one intent (config
  `render.alert_tools`); dashboard panels render for Prometheus, Grafana, and Wavefront.
- **Live oracle in CI** — run `challenge-run --oracle '<llm-cli>'` against a hosted Copilot/
  Claude CLI so the judgment-call gate runs unattended.

Recently landed: the broader **authoring skill set** (`sre-blast-radius` / `sre-prr-review` /
`sre-estate`) and a **consumer side** (`sre-incident-response` skill + `sre-oncall` agent), and
the **live challenge loop** (`sre-kb challenge-run`).

Known limitations (documented, not bugs): variable-topic egress (non-literal Kafka topics)
and cross-file call-graph beyond a single handler body are out of scope for the per-file
AST model.

## Quickstart (dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                                   # the test suite (261 tests)
sre-kb schema list                                          # the kind registry

# scan -> scaffold -> validate -> render -> stage a PR tree (dry-run)
sre-kb run --target tests/fixtures/sample-spring-pcf --run demo --to-stage publish
sre-kb findings --run demo                                  # ranked risk digest

# repo-neutrality: the same engine on a .NET/Steeltoe service
sre-kb run --target tests/fixtures/sample-dotnet-steeltoe --run net --to-stage validate

# cross-service co-tenancy blast radius
sre-kb estate --target tests/fixtures/sample-spring-pcf --target tests/fixtures/sample-billing-pcf
```

### Offline / air-gapped install

`make offline-wheel` (or `scripts/build-offline.sh`) builds a self-contained wheelhouse — the engine
wheel plus every runtime dependency — under `dist/wheels/`. Schemas and the default config ship inside
the wheel as package data, so a disconnected runner (e.g. PCF) installs with no index:

```bash
make offline-wheel
pip install --no-index --find-links dist/wheels sre-kb
```

### Dev container

VS Code / Codespaces can also open this repo in the included dev container. It uses Python 3.13 (the
working base; the supported floor is still 3.11) and runs `pip install -e ".[dev]"` after creation,
so `pytest -q` and `ruff check src tests` work from a clean container without local Python setup.
