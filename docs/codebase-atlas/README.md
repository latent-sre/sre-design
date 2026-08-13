# Codebase atlas

## Snapshot

| Field | Value |
|---|---|
| Repository | `sre-design` / Python package `sre-kb` |
| Baseline commit | `1713dc5f64d293c0e3b8a4bccf56809eecdd8406` |
| Baseline commit date | 2026-08-05 |
| Atlas date | 2026-08-13 |
| Scope | Explicit projects/roots in [`.sre/atlas.yaml`](../../.sre/atlas.yaml), plus reviewed docs and operational evidence |
| Excluded | `.git/`, `.venv/`, `.work/`, caches, generated artifacts, and live systems |
| Machine snapshot | [`generated/atlas.json`](generated/atlas.json), with bundled schema and file hashes |
| Current evidence ceiling | Structured manifests, AST/tree-sitter resolution, and a fresh local engine self-scan; no live runtime import |

The source model was frozen before the design documents were used for intent comparison. The local
Python 3.12 virtual environment was stale, so validation moved to an isolated Python 3.13.14
environment under ignored `.work/`. The clean self-scan completed with 157 facts and 72 artifacts
(66 verified, 6 needs-review). Its artifacts aggregate bundled test fixtures under a fixture-derived
service identity, so they confirm engine execution and output contracts—not this repository's
business-service topology. See [OPERATIONS.md](OPERATIONS.md).

## System in one sentence

`sre-kb` is a model-neutral Python CLI that statically collects provenance-bearing SRE facts from a
target repository, scaffolds and validates schema-governed knowledge-base artifacts, exchanges
bounded judgment tasks with an LLM/operator, and renders/publishes operational projections.
[`STATIC_EXTRACTED`: `src/sre_kb/pipeline/orchestrator.py:48-334`,
`src/sre_kb/llm/provider.py:1-42`]

## Choose a tour

| You are… | Start here | Then |
|---|---|---|
| New contributor | [STACK.md](STACK.md) | [STRUCTURE.md](STRUCTURE.md) → [OPERATIONS.md](OPERATIONS.md) |
| Engineer planning a change | [ARCHITECTURE.md](ARCHITECTURE.md) | [DEPENDENCIES.md](DEPENDENCIES.md) → the package and tests named by [STRUCTURE.md](STRUCTURE.md) |
| Operator diagnosing a run | [OPERATIONS.md](OPERATIONS.md) | [ARCHITECTURE.md](ARCHITECTURE.md#main-execution-path) → [CONCERNS.md](CONCERNS.md) |
| LLM/Agent Skill maintainer | [ARCHITECTURE.md](ARCHITECTURE.md#llm-and-engine-responsibilities) | `sre-codebase-cartographer` → `.github/skills/sre-codebase-atlas/` → `tests/test_skills.py` |
| Anyone exploring interactively | [Generated HTML atlas](generated/atlas.html) | Filter nodes, edges, scopes, owners, and explicit unknowns offline |

### A two-minute, non-developer tour

Think of `sre-kb` as an **evidence-to-operations assembly line**, not as a production service that
handles customer traffic:

1. **Read:** it reads a bounded checkout without running the target application's build.
2. **Describe:** it records small facts such as “this route calls that dependency,” each tied to the
   exact source lines that support it.
3. **Check resilience:** it identifies protections it can prove are present and flags bounded gaps
   such as a write without nearby idempotency, a message consumer without a dead-letter route, or a
   retry without configured backoff.
4. **Challenge:** schemas, provenance checks, safety checks, and an adversarial grounding pass decide
   whether each generated artifact is verified, needs review, or rejected.
5. **Explain:** it turns accepted artifacts into diagrams, plain-English flows, runbooks, alerts, and
   a staged publication tree.

Point the command directly at a checkout with `sre-kb human-report --target <repo>`. It safely scans
the repository and performs five deterministic passes that go from system purpose to flows,
dependencies and service destinations, resilience, and prioritized action. Use `--run <id>` to
report an existing validated run, or `--format json` when another tool needs the same model.

[`STATIC_EXTRACTED`: `src/sre_kb/pipeline/orchestrator.py:76-125,130-220`,
`src/sre_kb/render/plain.py:1-93`, `src/sre_kb/reporting/human_report.py`]

For a visual SRE view, go directly to the
[resilience lens](ARCHITECTURE.md#resilience-lens-for-operators). It separates **a pattern found in
code**, **a suspected or deterministic gap**, and **actual runtime proof** so an operator does not
mistake static analysis for production health.

## System map

The solid path is the deterministic engine. The dashed loop is the bounded LLM/operator exchange.

```mermaid
flowchart LR
  target["Target repository"] --> collect["Static collectors"]
  collect --> facts["Provenance facts"]
  facts --> scaffold["Schema scaffolder"]
  scaffold --> candidates["Candidate YAML"]
  candidates --> validate["Validation + challenge gates"]
  validate --> kb["Validated KB"]
  kb --> render["Render projections"]
  render --> publish["Dry-run tree / Forge"]

  validate -. "scan worklist" .-> skills["Agent Skills + operator/LLM"]
  skills -. "proposal files / verdicts" .-> ingest["Bounded ingest"]
  ingest -. "re-run / re-gate" .-> validate
```

Evidence: pipeline stages and handoffs are defined in
`src/sre_kb/pipeline/orchestrator.py:48-334`; the default model-free file provider and optional
subprocess provider are in `src/sre_kb/llm/provider.py:37-97`; render dispatch is in
`src/sre_kb/render/project.py:27-116`. [`STATIC_EXTRACTED`]

## Evidence model

This atlas uses the labels defined by the
[atlas evidence model](../../.github/skills/sre-codebase-atlas/references/evidence-model.md):

- `MANIFEST_DECLARED`, `STATIC_EXTRACTED`, and `STATIC_RESOLVED` for repository evidence;
- `ENGINE_CONFIRMED`, `RUNTIME_OBSERVED`, and `OPERATOR_CONFIRMED` for stronger confirmations;
- `INFERRED` and `UNKNOWN` when the evidence ceiling is explicit.

The successful self-scan and its run outputs are `ENGINE_CONFIRMED`; local interpreter/test results
are `RUNTIME_OBSERVED`. No deployed service or production behavior was observed.

## Known unknowns

- The deployed topology, traffic, latency, failure behavior, and current production configuration
  were not observed. [`UNKNOWN`: needs runtime telemetry/deployment evidence]
- The complete set of external users and service consumers cannot be derived from this repository
  alone. [`UNKNOWN`: needs fleet repositories, gateway records, contracts, or traces]
- Skills and agent instructions now consistently use the LLM-first, engine-enhances contract. The
  provider and orchestrator runtime still gate, reject, or downgrade artifacts, so instruction and
  executable trust boundaries remain intentionally distinct in this atlas.
- Project license terms and dependency license assertions remain unknown until maintainers choose a
  project license and import a reviewed SBOM/license source.

## Atlas pages

- [Technology stack](STACK.md)
- [Repository structure](STRUCTURE.md)
- [Architecture](ARCHITECTURE.md)
- [Dependencies](DEPENDENCIES.md)
- [Operations](OPERATIONS.md)
- [Concerns and open questions](CONCERNS.md)
- [Generated evidence, diagrams, schemas, and explorer](generated/README.md)
