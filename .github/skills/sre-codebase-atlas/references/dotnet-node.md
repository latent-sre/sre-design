# .NET and Node resolver guide

Use this guide only for .NET, Node.js, JavaScript, TypeScript, TSX, or mixed-stack targets.

## Evidence order

Keep four layers separate:

1. declared source and project configuration;
2. resolved package/build output;
3. runtime-observed topology;
4. operator-confirmed intent.

Do not upgrade a declaration to resolved evidence merely because a build would normally evaluate it.
Do not execute an untrusted repository's build, restore, package scripts, generators, or MSBuild
imports to obtain a graph.

## Node.js and TypeScript

List each package/workspace boundary explicitly in `.sre/atlas.yaml`. Include the package manifest,
the committed `package-lock.json` or npm shrinkwrap, and the applicable TypeScript/JavaScript
configuration.
Exclude `node_modules`, emitted bundles, framework caches, and coverage output from source roots.

The built-in adapters can record:

- `engines.node`, `engines.npm`, `packageManager`, module `type`, `main`, and workspace patterns;
- exact package nodes and direct/transitive edges from npm lockfileVersion 2 or 3;
- JavaScript, TypeScript, and TSX static imports/exports and literal `require()`/`import()` calls;
- relative files, `tsconfig`/`jsconfig` `baseUrl` plus `paths`, literal package `imports`, npm
  packages, and explicit `node:` built-ins.

Keep conditional exports/imports, plug-in discovery, computed paths, loader hooks, bundler aliases,
and non-literal dynamic loads `UNKNOWN` unless a dedicated resolver or reviewed runtime source
confirms them. A workspace glob is a declaration; it does not expand the atlas boundary by itself.

## .NET 8 and later SDK-style projects

Include `global.json`, the nearest applicable `Directory.Packages.props`, all configured `.csproj`
files, and either a committed `packages.lock.json` or an explicitly reviewed `project.assets.json`.
Record solution files as entry points, not as evaluated dependency truth.

The built-in adapters can record:

- .NET SDK version, roll-forward policy, and prerelease selection from `global.json`;
- project SDKs, target frameworks such as `net8.0`, runtime identifiers, nullable context, implicit
  usings, and output type from literal project properties;
- central `PackageVersion` values and project `PackageReference` declarations;
- exact direct/transitive NuGet package edges by target framework from lock/assets files;
- literal `ProjectReference` edges and C# namespace relationships.

MSBuild is an evaluated language. Conditions, imported props/targets, property-expanded paths,
solution-only dependencies, target-framework-specific items, and SDK-generated references can
change the real graph. Label raw project-file edges `MANIFEST_DECLARED`. Treat an
operator-reviewed `Microsoft.Build.Graph.ProjectGraph` export created with named global properties
and target frameworks as the preferred compiler/build-resolved project graph. Until such an import
exists, retain `resolver.msbuild-evaluation-required` or
`resolver.msbuild-project-graph-required` unknowns.

## Mixed monorepos

Use one non-overlapping project entry per meaningful package/project boundary. Do not collapse npm
workspaces and MSBuild projects into one unlabeled package graph. Render source, npm, NuGet,
project-reference, runtime, and incoming-consumer scopes independently before creating a small
cross-stack context view.
