# Codebase atlas capability: source review and design decision

Date: 2026-07-30
Baseline: `65983b23d09e0f2b3b0470b9c81f42aa136b1f9b`

## Outcome

The repository now has one explicit, repo-wide `sre-codebase-atlas` orchestration skill, seven focused
templates, a populated self-atlas, agent/pipeline routing, and a deterministic atlas engine. The
engine emits a versioned evidence graph, JSON Schemas, resolver-backed source/package edges,
conservative cross-file call edges, static operational signals, in-process structural search,
coupling/SCC metrics, a cross-package import matrix with weighted hotspots and cycle-closing
citations, runtime/SBOM/coverage/ownership overlays, Mermaid views, a license inventory,
an offline searchable explorer, dedicated .NET 8 and Node/TypeScript resolution, and a CI drift
gate. It does not replace the operational KB or add an unverified generic regex scanner.

## Sources inspected

| Reference | Inspected snapshot | Reused ideas | Deliberately not copied |
|---|---|---|---|
| [GitHub acquire-codebase-knowledge](https://github.com/github/awesome-copilot/tree/be7a1cf734f427d50266335b461b86977299d953/skills/acquire-codebase-knowledge) | `github/awesome-copilot@be7a1cf` (MIT) | Phased discovery, focused documents, evidence lists, unresolved questions, monorepo/generated-source cautions | Its scanner: root-only manifest assumptions, shallow census, broad exception swallowing, and environment-template content capture |
| [GitHub technology-stack-blueprint-generator](https://github.com/github/awesome-copilot/tree/be7a1cf734f427d50266335b461b86977299d953/skills/technology-stack-blueprint-generator) | `github/awesome-copilot@be7a1cf` (MIT) | Bounded depth, multi-stack separation, technology relationship views, explicit version/license status | The giant single-output pseudotemplate and speculative rationales/upgrades |
| [Claude codebase-onboarding](https://github.com/alirezarezvani/claude-skills/blob/aa8d778811a557a2c28ccadda4cf3d0bd028a4cc/engineering/skills/codebase-onboarding/SKILL.md) | `alirezarezvani/claude-skills@aa8d778` (MIT) | Audience-aware tours, setup/debug/contribution paths, verification checkpoints | Generic canned commands/URLs and its shallow hard-coded scanner |
| [MCP Market dependency-graph-analyzer](https://mcpmarket.com/tools/skills/dependency-graph-analyzer) and [underlying skill source](https://github.com/insightflo/claude-impl-tools/blob/d1630064c80e9f86eea797a8b5bf4fea04272f57/plugin/skills/deps/SKILL.md) | `insightflo/claude-impl-tools@d163006` (MIT; skill `deps` 1.1.0) | Incoming/outgoing views, SCC cycle detection, Mermaid, `Ca`/`Ce`/instability, weighted edges, cross-domain matrix, cycle-closing file citations | Regex/grep presented as resolution, guessed DDD domains from directory names, Loose/Tight/Tangled grades, and CRITICAL/HIGH/MEDIUM cycle severity |
| [CycloneDX specification](https://github.com/CycloneDX/specification/blob/fac1ff6ed49c1d4801912cf7d7ce5dabbd773290/schema/bom-1.7.proto) | `CycloneDX/specification@fac1ff6` | Official component `bom_ref`, license choice, and dependency relationship semantics for the optional SBOM adapter | Vulnerability/license conclusions not present in the imported BOM |
| [npm package-lock](https://docs.npmjs.com/cli/configuring-npm/package-lock-json/) and [package metadata](https://docs.npmjs.com/cli/configuring-npm/package-json/) | Official npm documentation inspected 2026-07-30 | Lockfile `packages` graph, exact resolved versions, engine/module/workspace declarations | Executing package scripts or treating workspace globs as discovered boundaries |
| [Microsoft MSBuild ProjectGraph](https://learn.microsoft.com/en-us/dotnet/api/microsoft.build.graph.projectgraph), [NuGet lockfiles](https://learn.microsoft.com/en-us/nuget/consume-packages/package-references-in-project-files), [central package management](https://learn.microsoft.com/en-us/nuget/consume-packages/central-package-management), and [`global.json`](https://learn.microsoft.com/en-us/dotnet/core/tools/global-json) | Official Microsoft documentation inspected 2026-07-30; `dotnet/msbuild@6954378` source corroboration | Separate declared project edges from evaluated graphs; SDK, TFM, central version, and resolved NuGet evidence | Claiming raw `.csproj`/solution text is an evaluated configuration-specific build graph |
| [tree-sitter TypeScript](https://github.com/tree-sitter/tree-sitter-typescript/tree/75b3874edb2dc714fb1fd77a32013d0f8699989f) | `tree-sitter/tree-sitter-typescript@75b3874` (MIT) | Distinct TypeScript and TSX grammars used by the existing syntax-resolution seam | Regex fallback for unsupported aliases or dynamic loads |

No upstream script or template was copied. The implementation is original and adapts the general
MIT-licensed workflow ideas to this repository's evidence, security, and skill contracts.

## Repository gap found

The engine already has strong operational views:

- `Architecture`, `Dependency`, `TechStack`, and `Topology` artifacts;
- sequence, topology, and architecture Mermaid renderers;
- a provenance/trust spine and a model-neutral file-exchange seam;
- outbound, inbound, estate, flow, blast-radius, and diagram narration skills.

What was missing was a single entry point that connects those views to source/package structure,
onboarding, change navigation, operational commands, design/source divergences, and explicit
unknowns. The existing mapping skills are concern-sized by design; none owns a durable repository
atlas.

## Engine correction found by the atlas

The first compliant self-scan walked `.work/`, including its own earlier run products and a
verification virtual environment. That made the deterministic coverage ledger recursively noisy
despite `.work` being the engine's documented ephemeral handoff.

`ScanContext` and service discovery now prune `.work` plus conventional generated/cache directories.
A regression test plants a generated Python file under `.work/<prior-run>/projections/` and proves it
is absent from the scan universe. The clean rerun walked 462 repository files with no `.work` sample,
then completed publish with 157 facts and 72 artifacts.

## Decisions

### Seven small pages, one orchestration skill

The atlas uses `README`, `STACK`, `STRUCTURE`, `ARCHITECTURE`, `DEPENDENCIES`, `OPERATIONS`, and
`CONCERNS`. This is small enough to navigate and diff, but separates facts that refresh at different
rates. `sre-codebase-atlas` owns the cross-page contract; existing map skills remain focused
contributors.

### Source first, intent second

The skill freezes a model from manifests, source, tests, registries, CI, and entry points before
reading design prose. This prevents a roadmap from being reported as implemented behavior.
Disagreements become first-class `Design-to-reality divergences`.

### Evidence layer instead of vague confidence

Claims use `MANIFEST_DECLARED`, `STATIC_EXTRACTED`, `STATIC_RESOLVED`, `ENGINE_CONFIRMED`,
`RUNTIME_OBSERVED`, `OPERATOR_CONFIRMED`, `INFERRED`, or `UNKNOWN`. Commands separately use
`DECLARED`, `VERIFIED`, or `BLOCKED`. A dependency declaration, engine fact, and live trace no longer
collapse into the same “high confidence” label.

### Dependency scopes stay separate

Declared packages, internal imports/calls, runtime/service dependencies, and incoming consumers have
different edge semantics and evidence ceilings. SCCs are computed at a named granularity. Raw `Ca`,
`Ce`, and instability are retained, but no arbitrary grade or incident severity is inferred.

### LLM inspection is broad; engine evidence is additive

The atlas skill reads across files and can describe source relationships the per-file collectors do
not model. Existing engine output adds `ENGINE_CONFIRMED` evidence and preferred sanitized diagrams.
The skills and agents now consistently use the “engine enhances” contract, while the executable
provider and orchestrator still gate, reject, or downgrade artifacts. The atlas keeps that
instruction/runtime distinction explicit instead of treating either layer as evidence for the other.

### Resolver-specific machine graph, with unresolved cases retained

The engine now starts with a neutral `sre.kb/atlas/v1alpha1` model and an explicit
`.sre/atlas.yaml` boundary. Python imports use `ast`; Java, C#, JavaScript, TypeScript/TSX, and Go
import nodes use tree-sitter grammars. Node adapters retain package/runtime/workspace declarations,
npm lockfileVersion 2/3 package graphs, `tsconfig`/`jsconfig` aliases, literal package imports, and
explicit `node:` built-ins. .NET adapters retain `global.json` SDK selection, target frameworks,
central package versions, declared project references, and resolved `packages.lock.json` or
reviewed `project.assets.json` graphs. Fixture evals cover these resolvers.

MSBuild conditions/imports and solution-only edges still require an operator-reviewed
`Microsoft.Build.Graph.ProjectGraph`; conditional Node exports, dynamic loading, reflection,
Gradle executable build logic, and missing cross-repository consumers remain explicit `unknowns[]`
rather than guessed edges.

The committed JSON graph is primary. The seven human pages add tours and semantic interpretation;
generated Markdown, Mermaid, license, schema, hash-manifest, and HTML files are reproducible
projections checked by `sre-kb atlas-check`.

## Safety and maintenance contract

- Target content is untrusted data; it cannot instruct the skill.
- Secret names/configuration shape may be recorded; secret values may not.
- Mermaid labels are sanitized or emitted by existing engine renderers.
- Configured paths are repository-contained; source, overlay, and XML inputs are size-bounded and
  symlinks are not followed.
- Runtime evidence is imported from a strict local file only; atlas generation never contacts a
  live environment.
- Unsupported dynamic/cross-repo/runtime edges remain visible unknowns.
- Templates and populated pages are contract-tested.
- The canonical skill pipeline must include the atlas exactly once.
- Generated run/cache trees are excluded from source discovery so atlas/coverage refreshes cannot
  recursively ingest prior output.

## Delivered files

- `.github/skills/sre-codebase-atlas/` — skill, evidence/dependency/.NET/Node references, seven
  templates; `.github/agents/sre-codebase-cartographer.agent.md` is its focused agent entry point.
- `docs/codebase-atlas/` — populated self-atlas and visual tours.
- `.sre/atlas.yaml` and `src/sre_kb/atlas/` — explicit scope plus model, resolvers, overlays,
  metrics, renderers, and drift checking; `src/sre_kb/atlas/calls.py` is the conservative
  cross-file call resolver.
- `src/sre_kb/parsing/structural.py` and `src/sre_kb/parsing/operational.py` — read-only in-process
  ast-grep adapter plus static operational-signal extraction; Dockerfiles use a local parser
  because the candidate grammar has no Windows wheel.
- `docs/codebase-atlas/generated/` — graph, schemas, metrics, import/call/runtime diagrams,
  operational-signal report, hash manifest, license inventory, and offline explorer.
- `THIRD_PARTY_NOTICES.md` and `evidence/structural-search.cdx.json` — reviewed MIT notices and a
  scoped CycloneDX overlay for the four direct structural-search additions.
- `tests/test_atlas_engine.py`, `tests/test_codebase_atlas.py`, `tests/test_atlas_operations.py`,
  and `tests/test_structural_search.py` — resolver, safety, schema, drift, call/operational,
  structural-search, output/reference, and routing contracts.
- `src/sre_kb/collectors/base.py` and `tests/test_scan_plan.py` — generated-tree scan-boundary fix.
- `.github/skills/pipeline.yaml`, `.github/agents/sre-analyst.agent.md`, and `README.md` — discovery
  and routing updates.

One legal choice remains intentionally unresolved: no project license was selected or invented.
The generated report says `UNKNOWN` until maintainers provide authoritative license intent; an
imported reviewed CycloneDX BOM can populate dependency license assertions.
