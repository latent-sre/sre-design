# Repository structure

## Top-level map

```text
sre-design/
├── .github/
│   ├── agents/                 Copilot agent roles
│   ├── skills/                 Agent Skills and canonical pipeline.yaml
│   └── workflows/              CI, lockfile audit, and secret scan
├── AGENTS.md                   Codex routing and repository evidence rules
├── docs/                       Design, roadmap, scope, and this atlas
├── scripts/                    Offline-wheel helper
├── src/sre_kb/
│   ├── collectors/             Bounded static extraction by stack/concern
│   ├── parsing/ + models/      Syntax model and provenance-bearing facts
│   ├── synth/                  Facts -> schema-shaped candidates/worklists
│   ├── pipeline/               Stage orchestration and bounded LLM ingests
│   ├── validation/             Schema, provenance, cross-ref, safety, challenge
│   ├── render/ + publish/      Diagrams/docs and staged/live Forge publication
│   ├── estate/ + drift/        Cross-service and change views
│   ├── schemas/ + registry.py  Artifact contracts and dispatch backbone
│   └── cli.py                  Command entry point
├── tests/                      Unit, adversarial, fixture, integration, contract tests
├── tools/                      Skill linter and schema-reference generator
├── Makefile                    Declared developer operations
├── pyproject.toml              Package/build/tool contract
└── requirements.lock           Resolved hash-pinned dependency set
```

This is a purpose-oriented map, not an exhaustive directory listing.
[`STATIC_EXTRACTED`: repository tree at baseline commit]

## Atlas-owned paths

| Path | Responsibility |
|---|---|
| `.sre/atlas.yaml` | Authoritative project roots, test roots, manifests, exclusions, evidence inputs, and generated-output boundary |
| `src/sre_kb/atlas/model.py` | Strict `sre.kb/atlas/v1alpha1` and runtime-evidence contracts |
| `src/sre_kb/atlas/source.py` | Python AST and Java/C#/JavaScript/Go tree-sitter dependency resolvers |
| `src/sre_kb/atlas/manifests.py` | Structured Python, Node, Maven, MSBuild, Go, and requirements adapters |
| `src/sre_kb/atlas/overlays.py` | Runtime, CycloneDX, Cobertura, CODEOWNERS, and optional Git-history overlays |
| `src/sre_kb/atlas/render.py` | JSON Schema, Markdown, Mermaid, license report, and offline HTML projections |
| `docs/codebase-atlas/generated/` | Drift-gated machine snapshot and generated views; never hand-edited |

## Entry points

| Entry point | Purpose | Evidence |
|---|---|---|
| `sre-kb` | Installed CLI | `pyproject.toml:33-34`; `src/sre_kb/cli.py:1264-1269` |
| `sre-kb atlas` / `atlas-check` | Generate the graph or fail on projection drift | `src/sre_kb/cli.py`; `src/sre_kb/atlas/runner.py` |
| `sre_kb.pipeline.run` | Main scan/scaffold/validate/render/publish path | `src/sre_kb/pipeline/orchestrator.py:48-334` |
| `sre_kb.estate.run_estate` | Multi-service topology/co-tenancy analysis | `src/sre_kb/estate/runner.py:52` |
| `AGENTS.md` | Codex atlas, external-evidence, and LLM/runtime routing | `AGENTS.md:1-34` |
| `.github/copilot-instructions.md` | Repository-wide GitHub Copilot contract | `.github/copilot-instructions.md:1-55` |
| `.github/skills/pipeline.yaml` | Canonical Agent Skill inventory and phase routing | `.github/skills/pipeline.yaml:9-42` |
| `.github/skills/sre-codebase-atlas/SKILL.md` | Whole-repository visual atlas workflow | `.github/skills/sre-codebase-atlas/SKILL.md:1` |
| `.github/agents/sre-codebase-cartographer.agent.md` | Copilot entry point for atlas work | `.github/agents/sre-codebase-cartographer.agent.md:1` |
| `.github/agents/sre-analyst.agent.md` | Command-capable developer/analysis loop | `.github/agents/sre-analyst.agent.md:1-50` |
| `.github/agents/sre-target-scan.agent.md` | Read-only untrusted-target inspection | `.github/agents/sre-target-scan.agent.md:1` |
| `tools/lint_skills.py` | Skill shape, tool-surface, pipeline, and shared-reference gate | `tools/lint_skills.py:1-151` |

All rows are `STATIC_EXTRACTED`; whether an installed command currently executes is tracked in
[OPERATIONS.md](OPERATIONS.md).

## Generated and ephemeral paths

| Path | Lifecycle | Notes |
|---|---|---|
| `.work/<run>/facts/` | Ephemeral | JSONL fact handoff |
| `.work/<run>/candidates/` | Ephemeral | Scaffolded YAML and untrusted context packs |
| `.work/<run>/kb/` | Ephemeral run result | `verified/` and `needs-review/` trees |
| `.work/<run>/reports/` | Ephemeral run evidence | Validation, coverage, rejected artifacts |
| `.work/<run>/projections/` | Generated | Copilot instructions, catalog, runbooks, diagrams |
| `.work/<run>/pr/` | Generated staging tree | Dry-run or Forge publication input |
| `.pytest_cache/`, `.ruff_cache/`, `.hypothesis/`, `.coverage`, `__pycache__/` | Disposable cache/output | Listed by the Make clean target |
| `docs/codebase-atlas/` | Source-controlled documentation | Human-reviewable; refresh through `sre-codebase-atlas` |
| `docs/codebase-atlas/generated/` | Source-controlled generated evidence | Refresh with `sre-kb atlas`; verify with `sre-kb atlas-check` |

`RunLayout` owns the core handoff tree. Scan discovery now excludes `.work` and conventional
dependency/build/cache trees, preventing a rerun from ingesting its own artifacts. Publication
re-stages its PR tree cleanly and applies the secret gate before live publication.
[`STATIC_EXTRACTED`: `src/sre_kb/collectors/base.py:24-108`,
`src/sre_kb/workspace/layout.py:1-51`, `src/sre_kb/publish/pr_builder.py:246-332`]

## Change guide

| If you change… | Inspect/update together | Primary regression surface |
|---|---|---|
| A target-language detector | `collectors/<stack>/`, fact model/signatures, synth behavior | Stack fixture tests plus adversarial cases |
| An artifact field | schema, `schemas/registry.yaml`, synth, validation, renderer, skill references | `test_schema_*`, `test_registry_governance.py`, `test_skill_contract.py` |
| A pipeline stage or LLM task | `pipeline/`, `synth/worklist.py`, CLI, relevant skill/agent | worklist, provider, automation, and injection tests |
| A diagram shape | `render/diagrams.py`, renderer dispatch, narration ingest | `test_diagrams.py`, `test_render_robustness.py`, narration tests |
| A skill | its self-contained folder and `.github/skills/pipeline.yaml` | `tools/lint_skills.py`, `test_skills.py`, `test_lint_skills.py` |
| Publication behavior | `publish/`, Forge seam, security gates, config | publish, supply-chain, source-guard, secret-scan tests |
| This atlas contract | skill templates, seven atlas pages, source review note | `tests/test_codebase_atlas.py` |

## Evidence

- `src/sre_kb/collectors/__init__.py:11-85` — collector registry and scan ordering.
  [`STATIC_EXTRACTED`]
- `src/sre_kb/schemas/registry.yaml:1-101` — schema/renderer registry.
  [`MANIFEST_DECLARED`]
- `src/sre_kb/workspace/layout.py:1-51` — run handoff directories. [`STATIC_EXTRACTED`]
- `tests/test_skill_contract.py:1-89` — skill-to-engine field contract.
  [`STATIC_EXTRACTED`]
- `Makefile:28-29` — declared cache/output cleanup list. [`MANIFEST_DECLARED`]
