# Concerns and open questions

## Confirmed risks

| Concern | Consequence | Evidence | Practical next step |
|---|---|---|---|
| Project license and dependency licenses outside the structural-search scope are not authoritative | Distribution/reuse review is incomplete beyond the reviewed additions | No root `LICENSE*` or `project.license`; the scoped SBOM and notices cover only four direct MIT structural-search dependencies | Maintainers choose the project license and expand the reviewed SBOM/license inventory before distribution |
| No configured CODEOWNERS candidate exists | Ownership and reviewer overlays cannot name accountable teams | `overlay.codeowners-missing` in the generated atlas | Add a reviewed CODEOWNERS file; do not invent a team handle |
| Two package-level dependency SCCs cross intended subsystem boundaries | Package extraction/ownership changes can have broad coordination cost | 141-module / 451-edge AST import analysis; see [DEPENDENCIES.md](DEPENDENCIES.md#cycles) | Track the SCCs; only refactor with concrete change/test evidence |
| External consumers are not knowable from this checkout | Change-impact analysis can understate blast radius | Callers live in fleet repos/gateway/contracts/traces | Run `sre-kb estate` across known repos and add gateway/trace evidence |

The coupling concern is not assigned an incident severity: no build failure, runtime fault, or change
delay was supplied.

### Resilience interpretation risks

| Risk when using the atlas for operations | Guardrail in this atlas |
|---|---|
| Treating a detected annotation as proof that protection works under load | Presence, parameter completeness, runtime behavior, and operator intent are reported as separate evidence scopes |
| Treating a static absence as exhaustive | Each gap names its checked scope; dynamic wiring, platform policy, and out-of-repository controls remain unknown |
| Treating a clean scan as a health check | The operator view explicitly redirects current-health questions to telemetry, deployment state, and SLO evidence |
| Auto-acting on model judgment | Judgment-only gaps remain `needs-review`; deterministic confirmation is additive and the runtime gates can still downgrade or reject artifacts |

[`STATIC_EXTRACTED`: `src/sre_kb/collectors/llm/gap_finder.py:58-83`,
`src/sre_kb/pipeline/orchestrator.py:94-110,171-220`]

## Resolved during this refresh

- Windows subprocess commands no longer pass through POSIX `shlex`; native command lines preserve
  backslashes/quoting while the prompt remains on stdin and `shell=False`.
- Oracle tests use a cross-platform Python echo process instead of Unix `cat`.
- UTF-8 generated artifacts are read explicitly as UTF-8.
- Symlink safety tests are capability-aware; the full Windows gate is green with 873 passes, two
  privilege-dependent skips, and 91.10% coverage.
- README/operations guidance now gives a direct Python 3.13 PowerShell environment path, so a stale
  older `.venv` is not mistaken for product behavior.
- In-process structural search, Bash/SQL/YAML operational grammars, conservative cross-file call
  edges, and fenced runbook hints are covered by focused regression tests. No daemon or target
  build is involved.
- The four direct structural-search additions have reviewed MIT notices and a scoped CycloneDX
  evidence file; this does not choose a license for `sre-kb` itself.

## Design-to-reality divergences

### LLM-first skill contract and engine runtime still diverge

The Copilot instructions, skills, and agents now consistently direct the LLM to produce governed
cross-file analysis while the engine enhances supported findings. The executable
`src/sre_kb/llm/provider.py` and main orchestrator still re-ground, gate, reject, or downgrade
artifacts on their existing ingestion path.

Impact: instruction-facing analysis and executable ingestion currently have different trust
boundaries. Treat LLM-authored findings as governed analysis, report engine confirmation or
disagreement separately, and do not claim the runtime gate has been removed. Aligning runtime
behavior with the skill contract requires a separately reviewed behavior change and trust-boundary
tests.

### Collector overview text lags collector coverage

The module docstring in `src/sre_kb/collectors/__init__.py:1-7` names Java and C# AST coverage, while
the enabled collector registry at lines 52-76 also includes Python/FastAPI, Node/Express, and Go.

Impact: code readers can underestimate supported stacks. Update the docstring during the next
collector documentation refresh; the executable registry remains the working source of truth.

### Direct root self-scan aggregates bundled service fixtures

The successful self-scan identified the synthetic service as `billing-service` and combined Java,
.NET, Python, Node, and Go fixture components. This is expected from `run --target .`, which treats
the root as one scan context, but it is not a truthful topology for the engine repository.

Impact: engine artifacts are valid execution evidence but cannot replace the source-first atlas.
Use `run-plan`/scoped targets for a multi-service repository and keep test fixtures excluded from
business-topology interpretation.

## Unknowns

- Whether baseline Linux CI is currently green at this exact commit. A CI definition and a Windows
  run are not a current Linux job result.
- Which organizations actively consume the package, generated KB, or published projections.
- Current production traffic, topology, SLOs, and incident modes for any target repository.
- Whether every tree-sitter grammar and locked artifact supports all required offline platforms.
- Which trusted .NET repositories can supply reviewed, configuration-specific MSBuild
  `ProjectGraph` exports for conditions/imports that raw project files cannot resolve.
- Which Node monorepos use conditional exports, non-npm lock formats, loader hooks, or bundler
  aliases beyond the built-in npm/TypeScript resolver boundary.
- Which license the maintainers intend for this repository.
- Whether the large package SCC is an intentional modular-monolith trade-off or a refactoring target.

## Questions for maintainers

1. Should runtime ingestion change to match the adopted LLM-first skill contract, or should the
   design explicitly retain artifact gating as a separate executable trust boundary?
2. Which evidence should be authoritative when a cross-file LLM finding is supported by source but
   the current deterministic engine cannot re-derive it?
3. Is `sre-kb` intended for external distribution? If yes, which project license and SBOM/license
   policy apply?
4. Which real service repositories and runtime signals should form the first atlas/engine accuracy
   pilot?
5. Are the pipeline/synth/validation/render/publish feedback edges accepted boundaries, or should a
   lower-level artifact protocol break the package SCC?

## Refresh triggers

Refresh the atlas when any of these change:

- `pyproject.toml`, `requirements.lock`, CI, packaging, or the Python floor;
- pipeline stages, `LLMProvider`, trust/gating behavior, or the LLM-first plan status;
- schema registry, collector registry, package boundaries, or more than a small import refactor;
- skill pipeline, atlas templates, agent routing, renderers, or publication seams;
- a real fleet/runtime pilot supplies `ENGINE_CONFIRMED`, `RUNTIME_OBSERVED`, or
  `OPERATOR_CONFIRMED` evidence;
- the baseline commit changes materially or six months pass without review.

## Evidence

- `docs/LLM-FIRST-PORT.md:1-21,92-125` — intended design. [`MANIFEST_DECLARED`]
- `src/sre_kb/llm/provider.py:1-20` and `pipeline/orchestrator.py:172-257` — current gate.
  [`STATIC_EXTRACTED`]
- `AGENTS.md`, `.github/copilot-instructions.md`, `.github/skills/map-architecture/SKILL.md`, and
  `.github/agents/sre-analyst.agent.md` — adopted instruction-facing engine-enhances contract.
  [`STATIC_EXTRACTED`]
- `src/sre_kb/collectors/__init__.py:1-76` — overview/registry mismatch.
  [`STATIC_EXTRACTED`]
- `pyproject.toml`, `THIRD_PARTY_NOTICES.md`, and `evidence/structural-search.cdx.json` — project
  license gap plus the reviewed direct structural-search license declarations.
  [`MANIFEST_DECLARED` / `STATIC_EXTRACTED`]
- Local Python 3.13.14 verification and clean self-scan reports — portability fixes, 873 passing
  tests, two capability skips, 91.10% coverage, artifact counts, and fixture-derived target identity.
  [`RUNTIME_OBSERVED` / `ENGINE_CONFIRMED`]
- [`generated/atlas.json`](generated/atlas.json) and
  [`generated/licenses.json`](generated/licenses.json) — resolver unknowns, ownership gap, and
  license status. [`ENGINE_CONFIRMED`]
