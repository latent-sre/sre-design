# Dependency analysis rules

One graph cannot faithfully represent every kind of dependency. Keep these scopes separate.

## Graph scopes

1. **Declared package graph** — manifest and lockfile dependencies.
2. **Source import graph** — resolver-backed imports between files/modules/packages.
3. **Static call graph** — conservative calls whose alias/type resolves to one repository target.
4. **Runtime graph** — service calls, datastores, brokers, queues, caches, external APIs, and bindings.
5. **Incoming graph** — in-repo callers plus fleet consumers visible in sibling repos, gateway data,
   contracts, or traces.

Never mix a Python import, a database binding, and an HTTP caller into one unlabeled edge vocabulary.

## Resolution quality

Prefer, in order:

1. compiler/build/package-manager graphs;
2. language-aware parsers with path-alias and workspace resolution;
3. syntax-aware extraction;
4. text search as candidate discovery only.

Plain import regexes miss multiline syntax, aliases, re-exports, generated modules, build tags,
conditional imports, and reflection. If only text search is available, label edges `INFERRED` and do
not claim exhaustiveness.

The built-in resolver matrix is deliberately finite:

| Input | Resolver |
|---|---|
| Python source | Python `ast`, including exact relative-import resolution |
| Python, Java, C#, JavaScript, TypeScript/TSX, Go calls | imports/aliases or declared field types must select one repository target; ambiguity stays unknown |
| Java, C#, JavaScript, TypeScript/TSX, Go source | tree-sitter syntax nodes; local path/package resolution where the language contract permits |
| SRE structural discovery | read-only in-process ast-grep over an explicit built-in-language allowlist; never expose target grammar registration or rewrites |
| Bash, SQL, YAML operational files | MIT grammar wheels and trusted queries under explicit `operationalRoots`; results are `STATIC_EXTRACTED` |
| Dockerfiles | narrow local instruction parser; do not require a grammar wheel that is unavailable on Windows |
| Node `package.json` + npm lock/shrinkwrap | declared runtime/workspace/module metadata plus lockfileVersion 2/3 resolved package edges |
| TypeScript `tsconfig.json`/`jsconfig.json` | JSONC-aware `baseUrl` and `paths` alias resolution |
| .NET `global.json`, `Directory.Packages.props`, `.csproj` | SDK selection, central versions, target frameworks, declared package/project edges |
| NuGet `packages.lock.json` or reviewed `project.assets.json` | resolved direct/transitive package graph by target framework |
| `pyproject.toml`, requirements/lock files, `pom.xml`, `go.mod` | format-specific structured adapters |
| CycloneDX JSON | component `bom-ref`, licenses, and `dependencies[].dependsOn` |
| MSBuild conditions/imports/solution-only dependencies, Gradle executable build logic, reflection, dynamic imports | explicit unresolved/unknown until an evaluated build graph or runtime input exists |

Never convert an unsupported row into a best-effort generic import regex.

## Direction

For edge `A -> B`, define it once: **A depends on B**.

- outgoing/efferent dependencies of A are its change and failure inputs;
- incoming/afferent dependencies of A are the consumers potentially affected by changing A.

A service cannot prove all external callers from its own repository. Name the missing fleet, gateway,
contract, or trace source rather than inventing consumers.

## Cycles

Use strongly connected components (SCCs), not visual inspection. Report:

- file/module SCCs from the most precise graph;
- package/domain SCCs only after explicitly describing the collapse rule;
- self-loops separately;
- whether type-only, test-only, or optional imports are included.

A package-level SCC can exist even when the file-level graph is acyclic. Do not flatten those into one
“circular dependencies” count.

## Coupling metrics

For each node:

- `Ca` (afferent coupling) = distinct nodes that depend on it;
- `Ce` (efferent coupling) = distinct nodes it depends on;
- `I` (instability) = `Ce / (Ca + Ce)`, or `n/a` when both are zero.

These are structural signals, not severity scores. Do not assign arbitrary A–F grades or label a node
“unhealthy” from `I` alone. Pair a concern with concrete change, build, ownership, or incident
evidence.

## Diagram rules

- Use stable, sanitized node identifiers and human-readable labels.
- Keep the full edge list in a table or machine-readable artifact when the overview diagram is
  intentionally simplified.
- Put edge meaning in the legend.
- Mark unknown or inferred edges differently from resolved/observed edges.
- Split diagrams when the result is unreadable at normal GitHub width.
