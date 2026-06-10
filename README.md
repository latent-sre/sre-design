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
- **An LLM behind the `LLMProvider` seam** — the *judgment* half. The LLM is a
  **pointer-generator, never a fact source**: it cites verbatim bytes, and the engine
  re-grounds every output and gates it (downgrade-only). The default transport is
  **GitHub Copilot in VS Code** (agent mode + the Agent Skills / custom agent / prompt
  files this repo ships; the engine embeds no model); any LLM CLI plugs into the same
  seam via `--oracle` for headless runs.

The full design lives in [`docs/DESIGN.md`](docs/DESIGN.md).

## Status

Working engine, tested offline (686 tests, ruff-clean) against bundled **Java/Spring**,
**.NET/Steeltoe**, **Python/FastAPI**, **Node/Express**, and **Go** fixtures — the same collectors
emit the same KB across stacks (repo-neutrality). [`docs/DESIGN.md`](docs/DESIGN.md) holds the
architecture; live status is tracked in [`docs/HYBRID-PLAN.md`](docs/HYBRID-PLAN.md) §8/§9.

Implemented:
- **AST-backed extraction** — code structure (classes, methods, calls, annotations,
  try/catch) is read from a tree-sitter model (Java, C#, Python, JavaScript, and Go —
  `parsing/code_model.py`) with per-class scoping and receiver→field-type call correlation; only
  config files use direct parsing. Python/FastAPI, Node/Express, and Go (gin) emit the same facts
  (endpoints, egress, tech stack) from the AST so the unchanged scaffolder produces the same KB.
  Confidence is
  signal-derived.
- **Trust tiers (provenance)** — every evidence item carries a `source_tier` (`ast`
  deterministic | `llm`), rolled up per artifact in the validation report. Tier-B proposals stay
  fenced unless the engine independently confirms them with a deterministic rule at the cited bytes.
- **LLM gap-finder (Tier-B, spike)** — Copilot proposes resiliency gaps the AST missed
  (e.g. a client with no timeout); the engine locates each, stamps `path:line:hash`
  (`source_tier=llm`), and re-derives/refutes it via the shared `signatures` library. Refutation
  gaps land `ResiliencyGap` / `needs-review`; confirmation gaps can graduate to Tier-A when the
  deterministic rule fires. The first real-Copilot sample validation measured 4/4 recall and no
  false-positive survivors; service-scale noise remains open. Run via `sre-kb gap-finder`; the
  measurement recipe is in [`docs/SCOPE-AND-COVERAGE.md`](docs/SCOPE-AND-COVERAGE.md) §9.
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
  read-only `sre-target-scan` agents and the `sre-*`/`map-*`/`generate-*` Agent Skills that *build*
  the KB — `/sre-autopilot` launches the whole loop in one invocation) and a **consumer** side
  (the `sre-oncall` agent + `sre-incident-response` skill that *use* a published KB during an
  incident). The canonical skill list is `.github/skills/pipeline.yaml`.
- **The whole LLM loop, automatable end-to-end:** every LLM task (gap discovery, boundary
  confirms, challenge adjudication, alert/runbook/architecture/contract/narrative drafting) lives
  in one scan-worklist manifest. `sre-kb worklist-run --oracle '<llm-cli>'` drives it through any
  LLM CLI on stdin, and `sre-kb autopilot` converges scan → provider → apply → re-scan in one
  command — the engine embeds no model; with no oracle everything defers to the manual IDE loop,
  exactly as offline. Accuracy is measurable the same way (`copilot-gap-validate --oracle`), the
  published repo carries a generated **scheduled drift workflow** (`sre-kb diff --from-kb`), and
  recurring confirmed findings graduate via `sre-kb graduation-draft` (LLM-drafted,
  engine-verified, human-merged).

## What's next

The roadmap is [`docs/HYBRID-PLAN.md`](docs/HYBRID-PLAN.md); §8 tracks status and §9 the post-spike
reassessment. Phases 0–3 (trust tiers, output + publish hardening, the status-aware trust spine, and
the Copilot challenge loop), the §7.6 schema governance, and the **Phase 4 gap-finder spike** have
landed. Phase 4 now has refutation probes (`missing-timeout`, `unguarded-critical-dependency`),
confirmation probes (`swallowed-failure`, `undocumented-job`), judgment routing, target-scoped config
probing, and a noise budget. The spike cleared the plan's make-or-break bar, and it is now **wired
into `sre-kb run`** (a `.sre/gap-proposals.json` is auto-detected and routed through the shared gate;
§9.3 item 1). The remaining order is **integrate before expand** (§9.3):

- **Scoped publish credential split** — wire the scoped publish role + CI so an unattended
  `--no-dry-run` publish (and `autopilot --oracle`) runs under least privilege; the no-credential
  scan role already landed. This is the remaining gate before live publish.
- **The measured pilot** — sweep real services through `copilot-gap-validate --oracle` against the
  stage-2 accuracy floors (`docs/SCOPE-AND-COVERAGE.md` §3) before trusting drafted output.

Recently landed: the **programmatic LLM loop** (S10: unified scan worklist + `worklist-run` +
`autopilot`, the scheduled drift workflow, one-command measurement, `graduation-draft`, and the
`map-architecture` channel — see HYBRID-PLAN §9.7), the **graduation loop**
(`sre-kb confirm-gap` → `sre-kb graduation-candidates`),
the Phase 5 **render-adapter breadth** (Prometheus/Splunk/Wavefront/AppDynamics/Grafana/ThousandEyes
alerts; Prometheus/Grafana/Wavefront dashboards), **drift detection** (`sre-kb diff`), the
**generate-phase skills** (`sre-generate-slos`, `sre-generate-dashboards`) plus `sre-security-posture`,
and **Node/Express + Go** collectors with AST endpoint extraction (five stacks).

Known limitations (documented, not bugs): variable-topic egress (non-literal Kafka topics)
and cross-file call-graph beyond a single handler body are out of scope for the per-file
AST model.

## Quickstart (dev)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                                                   # the test suite
sre-kb schema list                                          # the kind registry

# scan -> scaffold -> validate -> render -> stage a PR tree (dry-run)
sre-kb run --target tests/fixtures/sample-spring-pcf --run demo --to-stage publish
sre-kb findings --run demo                                  # ranked risk digest

# the whole loop in one command (any LLM CLI as the oracle; in VS Code use /sre-autopilot)
sre-kb autopilot --target tests/fixtures/sample-spring-pcf --oracle 'copilot -p'

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
