# Concerns and open questions

## Confirmed risks

| Concern | Consequence | Evidence | Practical next step |
|---|---|---|---|
| Project/dependency license terms are not authoritative | Distribution/reuse review lacks a legal answer | Generated identity inventory exists, but no root `LICENSE*`, `project.license`, or reviewed SBOM license assertion | Maintainers choose the project license and import/review a dependency SBOM/license source |
| No configured CODEOWNERS candidate exists | Ownership and reviewer overlays cannot name accountable teams | `overlay.codeowners-missing` in the generated atlas | Add a reviewed CODEOWNERS file; do not invent a team handle |
| Two package-level dependency SCCs cross intended subsystem boundaries | Package extraction/ownership changes can have broad coordination cost | 138-module / 439-edge AST import analysis; see [DEPENDENCIES.md](DEPENDENCIES.md#cycles) | Track the SCCs; only refactor with concrete change/test evidence |
| External consumers are not knowable from this checkout | Change-impact analysis can understate blast radius | Callers live in fleet repos/gateway/contracts/traces | Run `sre-kb estate` across known repos and add gateway/trace evidence |

The coupling concern is not assigned an incident severity: no build failure, runtime fault, or change
delay was supplied.

## Resolved during this refresh

- Windows subprocess commands no longer pass through POSIX `shlex`; native command lines preserve
  backslashes/quoting while the prompt remains on stdin and `shell=False`.
- Oracle tests use a cross-platform Python echo process instead of Unix `cat`.
- UTF-8 generated artifacts are read explicitly as UTF-8.
- Symlink safety tests are capability-aware; the full Windows gate is green with 848 passes, two
  privilege-dependent skips, and 91.26% coverage.
- README/operations guidance now gives a direct Python 3.13 PowerShell environment path, so a stale
  older `.venv` is not mistaken for product behavior.

## Design-to-reality divergences

### LLM-first migration is a plan, not uniform current behavior

`docs/LLM-FIRST-PORT.md` proposes that engine evidence enhances rather than gates LLM findings.
Current `src/sre_kb/llm/provider.py`, the main orchestrator, `map-architecture`, and
`sre-analyst.agent.md` still specify re-grounding/gating. `map-dependencies` and `map-callers` already
use the newer “engine enhances” framing.

Impact: an LLM maintainer can receive contradictory authority rules depending on the selected skill.
This atlas states both current and intended contracts rather than choosing silently. Complete the
planned migration as a separately reviewed behavior change, including tests for the resulting trust
boundary.

### Collector overview text lags collector coverage

The module docstring in `src/sre_kb/collectors/__init__.py:1-7` names Java and C# AST coverage, while
the enabled collector registry at lines 52-76 also includes Python/FastAPI, Node/Express, and Go.

Impact: code readers can underestimate supported stacks. Update the docstring when the broader
LLM-first migration touches this module; the executable registry remains the working source of truth.

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

1. Is `docs/LLM-FIRST-PORT.md` approved for implementation, or still a proposal requiring an
   architecture decision?
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
- `.github/skills/map-dependencies/SKILL.md:30-41` and
  `.github/skills/map-architecture/SKILL.md:17-34` — conflicting current skill contracts.
  [`STATIC_EXTRACTED`]
- `src/sre_kb/collectors/__init__.py:1-76` — overview/registry mismatch.
  [`STATIC_EXTRACTED`]
- `pyproject.toml:5-34` and root file inventory — license and runtime declarations.
  [`MANIFEST_DECLARED` / `STATIC_EXTRACTED`]
- Local Python 3.13.14 verification and clean self-scan reports — portability fixes, 848 passing
  tests, two capability skips, 91.26% coverage, artifact counts, and fixture-derived target identity.
  [`RUNTIME_OBSERVED` / `ENGINE_CONFIRMED`]
- [`generated/atlas.json`](generated/atlas.json) and
  [`generated/licenses.json`](generated/licenses.json) — resolver unknowns, ownership gap, and
  license status. [`ENGINE_CONFIRMED`]
