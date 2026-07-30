"""Conservative package/build manifest adapters.

These adapters parse structured manifest formats. Unsupported build logic is emitted as an
explicit unknown; source dependency relationships are never guessed with a generic regex.
"""

from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from sre_kb.atlas.config import AtlasConfig, ProjectConfig
from sre_kb.atlas.evidence import EvidenceStore, safe_xml_root
from sre_kb.atlas.graph import Graph
from sre_kb.atlas.model import (
    AtlasNode,
    AtlasUnknown,
    EvidenceClass,
    LicenseRecord,
    NodeType,
)

_PEP508_NAME = re.compile(r"^\s*([A-Za-z0-9](?:[-_.]*[A-Za-z0-9])*)")


@dataclass
class ManifestIndex:
    packages: dict[tuple[str, str], str] = field(default_factory=dict)
    scoped_packages: dict[tuple[str, str, str], str] = field(default_factory=dict)
    go_modules: dict[str, tuple[str, str]] = field(default_factory=dict)
    central_nuget_versions: dict[tuple[str, str], tuple[str, str, int]] = field(
        default_factory=dict
    )
    typescript_configs: dict[str, TypeScriptConfig] = field(default_factory=dict)
    node_imports: dict[str, dict[str, str]] = field(default_factory=dict)
    project_licenses: list[tuple[str, str]] = field(default_factory=list)
    licenses: list[LicenseRecord] = field(default_factory=list)

    def package(
        self,
        ecosystem: str,
        name: str,
        project: str | None = None,
    ) -> str | None:
        normalized = _normalize_name(ecosystem, name)
        if project is not None:
            return self.scoped_packages.get((project, ecosystem, normalized))
        return self.packages.get((ecosystem, normalized))

    def register_package(
        self,
        project: str,
        ecosystem: str,
        name: str,
        package_id: str,
    ) -> None:
        normalized = _normalize_name(ecosystem, name)
        self.scoped_packages[(project, ecosystem, normalized)] = package_id
        self.packages.setdefault((ecosystem, normalized), package_id)


@dataclass(frozen=True)
class TypeScriptConfig:
    base: str
    paths: dict[str, tuple[str, ...]]


def _manifest_priority(relative: str) -> tuple[int, str]:
    name = PurePosixPath(relative).name.lower()
    if name in {"global.json", "directory.packages.props", "tsconfig.json", "jsconfig.json"}:
        return (0, relative)
    if name in {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "packages.lock.json",
        "project.assets.json",
    }:
        return (1, relative)
    if name.endswith(".csproj"):
        return (3, relative)
    return (2, relative)


def collect_manifests(
    root: Path,
    config: AtlasConfig,
    store: EvidenceStore,
    graph: Graph,
) -> ManifestIndex:
    index = ManifestIndex()
    for project in config.projects:
        for relative in sorted(project.manifests, key=_manifest_priority):
            path = root / relative
            if not path.is_file() or path.is_symlink():
                graph.add_unknown(
                    AtlasUnknown(
                        code="manifest.missing",
                        message=f"Configured manifest does not exist: {relative}",
                        project=project.name,
                        path=relative,
                        neededEvidence="Restore the manifest or remove it from .sre/atlas.yaml.",
                    )
                )
                continue
            lower = path.name.lower()
            try:
                if lower == "pyproject.toml":
                    _pyproject(project, relative, store, graph, index)
                elif lower == "package.json":
                    _package_json(project, relative, store, graph, index)
                elif lower in {"package-lock.json", "npm-shrinkwrap.json"}:
                    _package_lock(project, relative, store, graph, index)
                elif lower in {"tsconfig.json", "jsconfig.json"}:
                    _typescript_config(project, relative, store, graph, index)
                elif lower == "pom.xml":
                    _pom(project, relative, store, graph, index)
                elif lower.endswith(".csproj"):
                    _csproj(project, relative, store, graph, index)
                elif lower == "directory.packages.props":
                    _directory_packages_props(project, relative, store, graph, index)
                elif lower == "global.json":
                    _global_json(project, relative, store, graph)
                elif lower == "packages.lock.json":
                    _nuget_lock(project, relative, store, graph, index)
                elif lower == "project.assets.json":
                    _project_assets(project, relative, store, graph, index)
                elif lower.endswith((".sln", ".slnx")):
                    graph.add_unknown(
                        AtlasUnknown(
                            code="resolver.msbuild-project-graph-required",
                            message=(
                                f"{relative} is a solution entry point, not an evaluated "
                                "MSBuild project graph."
                            ),
                            project=project.name,
                            path=relative,
                            neededEvidence=(
                                "Import an operator-reviewed Microsoft.Build.Graph ProjectGraph "
                                "export for configuration-specific project edges."
                            ),
                            evidence=[
                                store.evidence(
                                    relative,
                                    1,
                                    1,
                                    "atlas.manifest.msbuild-solution",
                                    EvidenceClass.unknown,
                                )
                            ],
                        )
                    )
                elif lower == "go.mod":
                    _go_mod(project, relative, store, graph, index)
                elif lower.startswith("requirements") and lower.endswith((".txt", ".lock")):
                    _requirements(project, relative, store, graph, index)
                elif lower.startswith("build.gradle") or lower.endswith(".gradle.kts"):
                    graph.add_unknown(
                        AtlasUnknown(
                            code="resolver.gradle-build-required",
                            message=(
                                f"{relative} may execute build logic; the atlas did not guess "
                                "dependencies from its text."
                            ),
                            project=project.name,
                            path=relative,
                            neededEvidence=(
                                "Import a Gradle-resolved dependency report or add a dedicated "
                                "resolver adapter."
                            ),
                            evidence=[
                                store.evidence(
                                    relative,
                                    1,
                                    1,
                                    "atlas.manifest.gradle",
                                    EvidenceClass.manifest_declared,
                                )
                            ],
                        )
                    )
                else:
                    graph.add_unknown(
                        AtlasUnknown(
                            code="resolver.manifest-unsupported",
                            message=f"No structured manifest adapter is registered for {relative}.",
                            project=project.name,
                            path=relative,
                            neededEvidence="Add a format-specific resolver adapter.",
                            evidence=[
                                store.evidence(
                                    relative,
                                    1,
                                    1,
                                    "atlas.manifest.unsupported",
                                    EvidenceClass.manifest_declared,
                                )
                            ],
                        )
                    )
            except (
                ET.ParseError,
                json.JSONDecodeError,
                tomllib.TOMLDecodeError,
                ValueError,
            ) as exc:
                graph.add_unknown(
                    AtlasUnknown(
                        code="manifest.parse-error",
                        message=f"Could not parse {relative}: {str(exc)[:200]}",
                        project=project.name,
                        path=relative,
                        neededEvidence="Correct the manifest syntax, then regenerate the atlas.",
                        evidence=[
                            store.evidence(
                                relative,
                                1,
                                1,
                                "atlas.manifest.parse-error",
                                EvidenceClass.manifest_declared,
                            )
                        ],
                    )
                )
    return index


def _project_id(project: ProjectConfig) -> str:
    return f"project:{project.name}"


def _annotate_project(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    annotations: dict,
    *,
    detector: str,
    line: int = 1,
    evidence_class: EvidenceClass = EvidenceClass.manifest_declared,
) -> None:
    evidence = store.evidence(relative, line, line, detector, evidence_class)
    graph.add_node(
        AtlasNode(
            id=_project_id(project),
            type=NodeType.project,
            name=project.name,
            project=project.name,
            group=project.name,
            annotations=annotations,
            evidence=[evidence],
        )
    )


def _normalize_name(ecosystem: str, name: str) -> str:
    value = name.strip()
    if ecosystem in {"pypi", "nuget", "npm"}:
        value = value.lower()
    if ecosystem == "pypi":
        value = re.sub(r"[-_.]+", "-", value)
    return value


def _normalize_relative(path: PurePosixPath) -> PurePosixPath | None:
    parts: list[str] = []
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return PurePosixPath(*parts)


def _resolved_package_id(ecosystem: str, name: str, version: str) -> str:
    return f"package:{ecosystem}:{_normalize_name(ecosystem, name)}@{version}"


def _add_package(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
    *,
    ecosystem: str,
    name: str,
    version: str | None,
    line: int,
    lifecycle: str,
    package_id: str | None = None,
    evidence_class: EvidenceClass = EvidenceClass.manifest_declared,
    detector: str | None = None,
    resolver: str | None = None,
    kind: str = "declares",
    annotations: dict | None = None,
) -> str:
    normalized = _normalize_name(ecosystem, name)
    package_id = (
        package_id
        or index.package(ecosystem, name, project.name)
        or f"package:{ecosystem}:{normalized}"
    )
    evidence = store.evidence(
        relative,
        line,
        line,
        detector or f"atlas.manifest.{ecosystem}",
        evidence_class,
    )
    node_annotations = {
        "ecosystem": ecosystem,
        "declaredBy": [project.name],
        "declaredVersions": [version or "unspecified"],
    }
    node_annotations.update(annotations or {})
    node = graph.add_node(
        AtlasNode(
            id=package_id,
            type=NodeType.package,
            name=name,
            group=ecosystem,
            version=version if evidence_class == EvidenceClass.static_resolved else None,
            annotations=node_annotations,
            evidence=[evidence],
        )
    )
    graph.add_edge(
        _project_id(project),
        node.id,
        kind=kind,
        scope="package",
        resolver=resolver or f"manifest:{ecosystem}",
        evidence=[evidence],
        annotations={"lifecycles": [lifecycle]},
    )
    index.register_package(project.name, ecosystem, name, package_id)
    return package_id


def _pyproject(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    data = tomllib.loads(store.text(relative))
    project_data = data.get("project")
    if not isinstance(project_data, dict):
        return
    dependencies = project_data.get("dependencies") or []
    if isinstance(dependencies, list):
        for requirement in dependencies:
            _python_requirement(project, relative, requirement, "runtime", store, graph, index)
    optional = project_data.get("optional-dependencies") or {}
    if isinstance(optional, dict):
        for group, requirements in optional.items():
            if isinstance(requirements, list):
                for requirement in requirements:
                    _python_requirement(
                        project,
                        relative,
                        requirement,
                        f"optional:{group}",
                        store,
                        graph,
                        index,
                    )
    license_value = project_data.get("license")
    if isinstance(license_value, str) and license_value.strip():
        index.project_licenses.append((license_value.strip(), relative))
    elif isinstance(license_value, dict):
        text = license_value.get("text")
        file_name = license_value.get("file")
        if isinstance(text, str) and text.strip():
            index.project_licenses.append(("DECLARED_TEXT_UNCLASSIFIED", relative))
        elif isinstance(file_name, str) and file_name.strip():
            index.project_licenses.append(
                ("FILE_REFERENCE_UNCLASSIFIED", f"{relative}:{file_name.strip()}")
            )


def _python_requirement(
    project: ProjectConfig,
    relative: str,
    requirement: object,
    lifecycle: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    if not isinstance(requirement, str):
        return
    match = _PEP508_NAME.match(requirement)
    if not match:
        graph.add_unknown(
            AtlasUnknown(
                code="manifest.pep508-unsupported",
                message=f"Could not identify a PEP 508 distribution name in {requirement!r}.",
                project=project.name,
                path=relative,
                neededEvidence="Use a standards-compliant resolved SBOM for this requirement.",
            )
        )
        return
    name = match.group(1)
    line = store.find_line(relative, requirement)
    version = _version_after_operator(requirement)
    _add_package(
        project,
        relative,
        store,
        graph,
        index,
        ecosystem="pypi",
        name=name,
        version=version,
        line=line,
        lifecycle=lifecycle,
    )


def _version_after_operator(requirement: str) -> str | None:
    for operator in ("===", "==", "~=", ">=", "<=", "!=", ">", "<"):
        if operator in requirement:
            value = requirement.split(operator, 1)[1].split(";", 1)[0].strip()
            return f"{operator}{value}" if value else None
    return None


def _requirements(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    for line_number, raw in enumerate(store.lines(relative), start=1):
        value = raw.strip().rstrip("\\").strip()
        if not value or value.startswith(("#", "-", "http://", "https://")):
            continue
        match = _PEP508_NAME.match(value)
        if not match:
            continue
        name = match.group(1)
        _add_package(
            project,
            relative,
            store,
            graph,
            index,
            ecosystem="pypi",
            name=name,
            version=_version_after_operator(value),
            line=line_number,
            lifecycle="locked",
        )


def _package_json(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    data = json.loads(store.text(relative))
    if not isinstance(data, dict):
        raise ValueError("package.json root must be an object")
    annotations: dict[str, object] = {}
    engines = data.get("engines")
    if isinstance(engines, dict):
        node_engine = engines.get("node")
        npm_engine = engines.get("npm")
        if isinstance(node_engine, str) and node_engine:
            annotations["nodeEngine"] = node_engine
        if isinstance(npm_engine, str) and npm_engine:
            annotations["npmEngine"] = npm_engine
    for source, target in (
        ("packageManager", "packageManager"),
        ("type", "moduleType"),
        ("main", "mainEntry"),
    ):
        value = data.get(source)
        if isinstance(value, str) and value:
            annotations[target] = value
    workspaces = data.get("workspaces")
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    if isinstance(workspaces, list):
        annotations["workspaces"] = sorted(
            value for value in workspaces if isinstance(value, str) and value
        )
    if annotations:
        _annotate_project(
            project,
            relative,
            store,
            graph,
            annotations,
            detector="atlas.manifest.package-json-runtime",
        )

    imports = data.get("imports")
    if isinstance(imports, dict):
        resolved_imports: dict[str, str] = {}
        for alias, target in imports.items():
            if isinstance(alias, str) and isinstance(target, str) and target.startswith("./"):
                normalized = _normalize_relative(PurePosixPath(relative).parent / target)
                if normalized is not None:
                    resolved_imports[alias] = normalized.as_posix()
        if resolved_imports:
            index.node_imports[project.name] = resolved_imports

    groups = {
        "dependencies": "runtime",
        "devDependencies": "development",
        "peerDependencies": "peer",
        "optionalDependencies": "optional",
    }
    for key, lifecycle in groups.items():
        dependencies = data.get(key) or {}
        if not isinstance(dependencies, dict):
            continue
        for name, version in dependencies.items():
            if not isinstance(name, str):
                continue
            line = store.find_line(relative, json.dumps(name))
            _add_package(
                project,
                relative,
                store,
                graph,
                index,
                ecosystem="npm",
                name=name,
                version=str(version) if version is not None else None,
                line=line,
                lifecycle=lifecycle,
            )


def _json_with_comments(text: str) -> object:
    """Parse JSONC without treating comment-like text inside strings as syntax."""
    without_comments: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            without_comments.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            without_comments.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            end = text.find("*/", index + 2)
            if end == -1:
                raise ValueError("unterminated block comment in JSON-with-comments")
            index = end + 2
            continue
        without_comments.append(char)
        index += 1

    value = "".join(without_comments)
    without_trailing_commas: list[str] = []
    in_string = False
    escaped = False
    for index, char in enumerate(value):
        if in_string:
            without_trailing_commas.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            without_trailing_commas.append(char)
            continue
        if char == ",":
            next_nonspace = next(
                (candidate for candidate in value[index + 1 :] if not candidate.isspace()),
                "",
            )
            if next_nonspace and next_nonspace in "}]":
                continue
        without_trailing_commas.append(char)
    return json.loads("".join(without_trailing_commas))


def _typescript_config(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    data = _json_with_comments(store.text(relative))
    if not isinstance(data, dict):
        raise ValueError("TypeScript configuration root must be an object")
    compiler = data.get("compilerOptions") or {}
    if not isinstance(compiler, dict):
        raise ValueError("compilerOptions must be an object")
    base_url = compiler.get("baseUrl", ".")
    if not isinstance(base_url, str) or "$(" in base_url:
        raise ValueError("TypeScript baseUrl must be a literal string")
    manifest_dir = PurePosixPath(relative).parent
    base = _normalize_relative(manifest_dir / base_url)
    if base is None:
        raise ValueError("TypeScript baseUrl escapes the repository")
    path_data = compiler.get("paths") or {}
    paths: dict[str, tuple[str, ...]] = {}
    if isinstance(path_data, dict):
        for alias, candidates in path_data.items():
            if not isinstance(alias, str) or not isinstance(candidates, list):
                continue
            values = tuple(
                candidate
                for candidate in candidates
                if isinstance(candidate, str) and candidate and "$(" not in candidate
            )
            if values:
                paths[alias] = values
    index.typescript_configs[project.name] = TypeScriptConfig(
        base=base.as_posix(),
        paths=paths,
    )
    _annotate_project(
        project,
        relative,
        store,
        graph,
        {
            "typescriptBaseUrl": base.as_posix(),
            "typescriptPathAliases": sorted(paths),
        },
        detector="atlas.manifest.tsconfig",
    )


def _package_lock(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    data = json.loads(store.text(relative))
    if not isinstance(data, dict):
        raise ValueError("npm lockfile root must be an object")
    lockfile_version = data.get("lockfileVersion")
    packages = data.get("packages")
    _annotate_project(
        project,
        relative,
        store,
        graph,
        {"npmLockfileVersion": str(lockfile_version or "unknown")},
        detector="atlas.manifest.npm-lock",
        evidence_class=EvidenceClass.static_resolved,
    )
    if not isinstance(packages, dict):
        graph.add_unknown(
            AtlasUnknown(
                code="resolver.npm-lock-v1-unavailable",
                message=(
                    f"{relative} has no packages table; the legacy nested npm lock graph "
                    "was not flattened."
                ),
                project=project.name,
                path=relative,
                neededEvidence="Regenerate a lockfileVersion 2 or 3 package-lock.json.",
                evidence=[
                    store.evidence(
                        relative,
                        1,
                        1,
                        "atlas.manifest.npm-lock-v1",
                        EvidenceClass.unknown,
                    )
                ],
            )
        )
        return

    entries: dict[str, tuple[str, str, str, dict]] = {}
    for raw_path, raw_metadata in packages.items():
        if not raw_path or not isinstance(raw_path, str) or not isinstance(raw_metadata, dict):
            continue
        name = _npm_lock_name(raw_path, raw_metadata)
        version = raw_metadata.get("version")
        if not name or not isinstance(version, str) or not version:
            continue
        package_id = _resolved_package_id("npm", name, version)
        line = store.find_line(relative, json.dumps(raw_path))
        evidence = store.evidence(
            relative,
            line,
            line,
            "atlas.manifest.npm-lock-package",
            EvidenceClass.static_resolved,
        )
        graph.add_node(
            AtlasNode(
                id=package_id,
                type=NodeType.package,
                name=name,
                group="npm",
                version=version,
                annotations={
                    "ecosystem": "npm",
                    "resolvedBy": [relative],
                    "resolvedVersions": [version],
                    "lockPaths": [raw_path],
                },
                evidence=[evidence],
            )
        )
        entries[raw_path] = (name, version, package_id, raw_metadata)

    root_metadata = packages.get("")
    if isinstance(root_metadata, dict):
        for group, lifecycle in (
            ("dependencies", "runtime"),
            ("devDependencies", "development"),
            ("optionalDependencies", "optional"),
        ):
            dependencies = root_metadata.get(group)
            if not isinstance(dependencies, dict):
                continue
            for dependency in dependencies:
                target = _npm_lock_target("", str(dependency), entries)
                if target is None:
                    continue
                name, _, package_id, _ = target
                line = store.find_line(relative, json.dumps(str(dependency)))
                evidence = store.evidence(
                    relative,
                    line,
                    line,
                    "atlas.manifest.npm-lock-direct",
                    EvidenceClass.static_resolved,
                )
                graph.add_edge(
                    _project_id(project),
                    package_id,
                    kind="resolved-dependency",
                    scope="package",
                    resolver="manifest:npm-lock",
                    evidence=[evidence],
                    annotations={"lifecycles": [lifecycle]},
                )
                index.register_package(project.name, "npm", name, package_id)

    for source_path, (_, _, source_id, metadata) in entries.items():
        dependencies = metadata.get("dependencies")
        if not isinstance(dependencies, dict):
            continue
        for dependency in dependencies:
            target = _npm_lock_target(source_path, str(dependency), entries)
            if target is None:
                continue
            _, _, target_id, _ = target
            line = store.find_line(relative, json.dumps(str(dependency)))
            evidence = store.evidence(
                relative,
                line,
                line,
                "atlas.manifest.npm-lock-edge",
                EvidenceClass.static_resolved,
            )
            graph.add_edge(
                source_id,
                target_id,
                kind="depends-on",
                scope="package",
                resolver="manifest:npm-lock",
                evidence=[evidence],
            )


def _npm_lock_name(path: str, metadata: dict) -> str | None:
    declared = metadata.get("name")
    if isinstance(declared, str) and declared:
        return declared
    marker = "node_modules/"
    if marker not in path:
        return None
    remainder = path.rsplit(marker, 1)[1]
    parts = remainder.split("/")
    if remainder.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0] if parts else None


def _npm_lock_target(
    source_path: str,
    dependency: str,
    entries: dict[str, tuple[str, str, str, dict]],
) -> tuple[str, str, str, dict] | None:
    base = PurePosixPath(source_path)
    while True:
        candidate = (base / "node_modules" / dependency).as_posix()
        if candidate in entries:
            return entries[candidate]
        if not base.parts:
            break
        base = base.parent
    direct = f"node_modules/{dependency}"
    return entries.get(direct)


def _pom(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    root = safe_xml_root(store.text(relative))
    for dependency in root.findall(".//{*}dependency"):
        group = dependency.findtext("{*}groupId")
        artifact = dependency.findtext("{*}artifactId")
        if not group or not artifact:
            continue
        version = dependency.findtext("{*}version")
        scope = dependency.findtext("{*}scope") or "runtime"
        name = f"{group}:{artifact}"
        line = store.find_line(relative, artifact)
        _add_package(
            project,
            relative,
            store,
            graph,
            index,
            ecosystem="maven",
            name=name,
            version=version,
            line=line,
            lifecycle=scope,
        )


def _directory_packages_props(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    root = safe_xml_root(store.text(relative))
    enabled = (root.findtext(".//{*}ManagePackageVersionsCentrally") or "").strip()
    annotations: dict[str, object] = {}
    if enabled:
        annotations["managePackageVersionsCentrally"] = enabled.lower() == "true"
    for item in root.findall(".//{*}PackageVersion"):
        name = item.get("Include") or item.get("Update")
        version = item.get("Version") or item.findtext("{*}Version")
        if not name or not version:
            continue
        line = store.find_line(relative, name)
        index.central_nuget_versions[(project.name, _normalize_name("nuget", name))] = (
            version,
            relative,
            line,
        )
    if annotations or index.central_nuget_versions:
        _annotate_project(
            project,
            relative,
            store,
            graph,
            annotations,
            detector="atlas.manifest.nuget-central",
        )


def _global_json(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
) -> None:
    data = _json_with_comments(store.text(relative))
    if not isinstance(data, dict):
        raise ValueError("global.json root must be an object")
    sdk = data.get("sdk")
    if not isinstance(sdk, dict):
        return
    annotations: dict[str, object] = {}
    for source, target in (
        ("version", "dotnetSdkVersion"),
        ("rollForward", "dotnetSdkRollForward"),
    ):
        value = sdk.get(source)
        if isinstance(value, str) and value:
            annotations[target] = value
    prerelease = sdk.get("allowPrerelease")
    if isinstance(prerelease, bool):
        annotations["dotnetSdkAllowPrerelease"] = prerelease
    if annotations:
        _annotate_project(
            project,
            relative,
            store,
            graph,
            annotations,
            detector="atlas.manifest.dotnet-global-json",
        )


def _resolved_nuget_node(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    *,
    name: str,
    version: str,
    target_framework: str,
    detector: str,
) -> str:
    package_id = _resolved_package_id("nuget", name, version)
    line = store.find_line(relative, json.dumps(name), default=store.find_line(relative, name))
    evidence = store.evidence(
        relative,
        line,
        line,
        detector,
        EvidenceClass.static_resolved,
    )
    graph.add_node(
        AtlasNode(
            id=package_id,
            type=NodeType.package,
            name=name,
            group="nuget",
            version=version,
            annotations={
                "ecosystem": "nuget",
                "resolvedBy": [relative],
                "resolvedVersions": [version],
                "targetFrameworks": [target_framework],
            },
            evidence=[evidence],
        )
    )
    return package_id


def _nuget_lock(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    data = json.loads(store.text(relative))
    if not isinstance(data, dict):
        raise ValueError("NuGet lockfile root must be an object")
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, dict):
        raise ValueError("NuGet lockfile dependencies must be an object")
    entries: dict[tuple[str, str], tuple[str, str, dict]] = {}
    for target_framework, raw_packages in dependencies.items():
        if not isinstance(target_framework, str) or not isinstance(raw_packages, dict):
            continue
        for name, raw_metadata in raw_packages.items():
            if not isinstance(name, str) or not isinstance(raw_metadata, dict):
                continue
            resolved = raw_metadata.get("resolved")
            package_type = raw_metadata.get("type")
            if (
                not isinstance(resolved, str)
                or not resolved
                or str(package_type).lower() == "project"
            ):
                continue
            package_id = _resolved_nuget_node(
                project,
                relative,
                store,
                graph,
                name=name,
                version=resolved,
                target_framework=target_framework,
                detector="atlas.manifest.nuget-lock-package",
            )
            entries[(target_framework, _normalize_name("nuget", name))] = (
                name,
                package_id,
                raw_metadata,
            )
            if str(package_type).lower() in {"direct", "centraltransitive"}:
                line = store.find_line(relative, json.dumps(name))
                evidence = store.evidence(
                    relative,
                    line,
                    line,
                    "atlas.manifest.nuget-lock-direct",
                    EvidenceClass.static_resolved,
                )
                graph.add_edge(
                    _project_id(project),
                    package_id,
                    kind="resolved-dependency",
                    scope="package",
                    resolver="manifest:nuget-lock",
                    evidence=[evidence],
                    annotations={"targetFrameworks": [target_framework]},
                )
                index.register_package(project.name, "nuget", name, package_id)
    for (target_framework, _), (_, source_id, metadata) in entries.items():
        package_dependencies = metadata.get("dependencies")
        if not isinstance(package_dependencies, dict):
            continue
        for dependency in package_dependencies:
            target = entries.get((target_framework, _normalize_name("nuget", str(dependency))))
            if target is None:
                continue
            line = store.find_line(relative, json.dumps(str(dependency)))
            evidence = store.evidence(
                relative,
                line,
                line,
                "atlas.manifest.nuget-lock-edge",
                EvidenceClass.static_resolved,
            )
            graph.add_edge(
                source_id,
                target[1],
                kind="depends-on",
                scope="package",
                resolver="manifest:nuget-lock",
                evidence=[evidence],
                annotations={"targetFrameworks": [target_framework]},
            )


def _project_assets(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    data = json.loads(store.text(relative))
    if not isinstance(data, dict):
        raise ValueError("project.assets.json root must be an object")
    targets = data.get("targets")
    if not isinstance(targets, dict):
        raise ValueError("project.assets.json targets must be an object")
    project_data = data.get("project")
    frameworks = project_data.get("frameworks") if isinstance(project_data, dict) else {}
    direct_names = (
        {
            _normalize_name("nuget", str(name))
            for framework in frameworks.values()
            if isinstance(framework, dict)
            for name in (framework.get("dependencies") or {})
        }
        if isinstance(frameworks, dict)
        else set()
    )
    entries: dict[tuple[str, str], tuple[str, str, dict]] = {}
    for target_framework, raw_packages in targets.items():
        if not isinstance(target_framework, str) or not isinstance(raw_packages, dict):
            continue
        for package_key, raw_metadata in raw_packages.items():
            if not isinstance(package_key, str) or not isinstance(raw_metadata, dict):
                continue
            if str(raw_metadata.get("type", "package")).lower() != "package":
                continue
            name, separator, version = package_key.rpartition("/")
            if not separator or not name or not version:
                continue
            package_id = _resolved_nuget_node(
                project,
                relative,
                store,
                graph,
                name=name,
                version=version,
                target_framework=target_framework,
                detector="atlas.manifest.nuget-assets-package",
            )
            normalized = _normalize_name("nuget", name)
            entries[(target_framework, normalized)] = (name, package_id, raw_metadata)
            if normalized in direct_names:
                line = store.find_line(relative, json.dumps(package_key))
                evidence = store.evidence(
                    relative,
                    line,
                    line,
                    "atlas.manifest.nuget-assets-direct",
                    EvidenceClass.static_resolved,
                )
                graph.add_edge(
                    _project_id(project),
                    package_id,
                    kind="resolved-dependency",
                    scope="package",
                    resolver="manifest:nuget-assets",
                    evidence=[evidence],
                    annotations={"targetFrameworks": [target_framework]},
                )
                index.register_package(project.name, "nuget", name, package_id)
    for (target_framework, _), (_, source_id, metadata) in entries.items():
        package_dependencies = metadata.get("dependencies")
        if not isinstance(package_dependencies, dict):
            continue
        for dependency in package_dependencies:
            target = entries.get((target_framework, _normalize_name("nuget", str(dependency))))
            if target is None:
                continue
            line = store.find_line(relative, json.dumps(str(dependency)))
            evidence = store.evidence(
                relative,
                line,
                line,
                "atlas.manifest.nuget-assets-edge",
                EvidenceClass.static_resolved,
            )
            graph.add_edge(
                source_id,
                target[1],
                kind="depends-on",
                scope="package",
                resolver="manifest:nuget-assets",
                evidence=[evidence],
                annotations={"targetFrameworks": [target_framework]},
            )


def _csproj(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    root = safe_xml_root(store.text(relative))
    manifest_dir = PurePosixPath(relative).parent
    project_file_id = f"project-file:{relative.lower()}"
    project_line = 1
    project_evidence = store.evidence(
        relative,
        project_line,
        project_line,
        "atlas.manifest.msbuild-project",
        EvidenceClass.manifest_declared,
    )
    sdk = root.get("Sdk")
    target_frameworks: list[str] = []
    for element_name in ("TargetFramework", "TargetFrameworks"):
        for element in root.findall(f".//{{*}}{element_name}"):
            value = (element.text or "").strip()
            if not value:
                continue
            if "$(" in value:
                _msbuild_evaluation_unknown(
                    project,
                    relative,
                    store,
                    graph,
                    value,
                    store.find_line(relative, value),
                )
                continue
            target_frameworks.extend(
                framework.strip() for framework in value.split(";") if framework.strip()
            )
    project_annotations: dict[str, object] = {}
    if sdk:
        project_annotations["projectSdks"] = [sdk]
    if target_frameworks:
        project_annotations["targetFrameworks"] = sorted(set(target_frameworks))
    for element_name, annotation in (
        ("Nullable", "nullable"),
        ("ImplicitUsings", "implicitUsings"),
        ("OutputType", "outputType"),
        ("RuntimeIdentifier", "runtimeIdentifiers"),
        ("RuntimeIdentifiers", "runtimeIdentifiers"),
    ):
        values = [
            value.strip()
            for element in root.findall(f".//{{*}}{element_name}")
            for value in (element.text or "").split(";")
            if value.strip() and "$(" not in value
        ]
        if values:
            project_annotations[annotation] = sorted(set(values))
    if project_annotations:
        _annotate_project(
            project,
            relative,
            store,
            graph,
            project_annotations,
            detector="atlas.manifest.msbuild-properties",
        )
    graph.add_node(
        AtlasNode(
            id=project_file_id,
            type=NodeType.project,
            name=PurePosixPath(relative).stem,
            project=project.name,
            path=relative,
            group="msbuild",
            annotations=project_annotations,
            evidence=[project_evidence],
        )
    )
    graph.add_edge(
        _project_id(project),
        project_file_id,
        kind="contains-project",
        scope="source",
        resolver="manifest:msbuild-declared",
        evidence=[project_evidence],
    )

    for dependency in root.findall(".//{*}PackageReference"):
        name = dependency.get("Include") or dependency.get("Update")
        if not name:
            continue
        version = dependency.get("Version") or dependency.findtext("{*}Version")
        central = index.central_nuget_versions.get((project.name, _normalize_name("nuget", name)))
        annotations: dict[str, object] = {}
        if not version and central is not None:
            version = central[0]
            annotations["centralVersionSources"] = [central[1]]
        condition = dependency.get("Condition")
        if condition:
            annotations["conditions"] = [condition]
            _msbuild_evaluation_unknown(
                project,
                relative,
                store,
                graph,
                condition,
                store.find_line(relative, condition),
            )
        line = store.find_line(relative, name)
        _add_package(
            project,
            relative,
            store,
            graph,
            index,
            ecosystem="nuget",
            name=name,
            version=version,
            line=line,
            lifecycle="runtime",
            package_id=index.package("nuget", name, project.name),
            annotations=annotations,
        )

    for reference in root.findall(".//{*}ProjectReference"):
        include = reference.get("Include")
        if not include:
            continue
        line = store.find_line(relative, include)
        if "$(" in include:
            _msbuild_evaluation_unknown(
                project,
                relative,
                store,
                graph,
                include,
                line,
            )
            continue
        target_path = _normalize_relative(manifest_dir / include.replace("\\", "/"))
        if target_path is None:
            raise ValueError(f"ProjectReference escapes the repository: {include}")
        target = target_path.as_posix()
        evidence = store.evidence(
            relative,
            line,
            line,
            "atlas.manifest.msbuild-project-reference",
            EvidenceClass.manifest_declared,
        )
        target_id = f"project-file:{target.lower()}"
        graph.add_node(
            AtlasNode(
                id=target_id,
                type=NodeType.project,
                name=target_path.stem,
                project=project.name,
                path=target,
                group="msbuild",
                evidence=[evidence],
            )
        )
        condition = reference.get("Condition")
        annotations = {"evaluation": "declared-not-evaluated"}
        if condition:
            annotations["conditions"] = [condition]
            _msbuild_evaluation_unknown(
                project,
                relative,
                store,
                graph,
                condition,
                line,
            )
        graph.add_edge(
            project_file_id,
            target_id,
            kind="project-reference",
            scope="source",
            resolver="manifest:msbuild-declared",
            evidence=[evidence],
            unresolved=not (store.root / target).is_file(),
            annotations=annotations,
        )


def _msbuild_evaluation_unknown(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    expression: str,
    line: int,
) -> None:
    graph.add_unknown(
        AtlasUnknown(
            code="resolver.msbuild-evaluation-required",
            message=(
                f"MSBuild expression or condition {expression!r} in {relative} was not evaluated."
            ),
            project=project.name,
            path=relative,
            neededEvidence=(
                "Import a reviewed Microsoft.Build.Graph result with the intended global "
                "properties and target framework."
            ),
            evidence=[
                store.evidence(
                    relative,
                    line,
                    line,
                    "atlas.manifest.msbuild-evaluation-required",
                    EvidenceClass.unknown,
                )
            ],
        )
    )


def _go_mod(
    project: ProjectConfig,
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    index: ManifestIndex,
) -> None:
    in_require = False
    module_path: str | None = None
    for line_number, raw in enumerate(store.lines(relative), start=1):
        value = raw.split("//", 1)[0].strip()
        if not value:
            continue
        if value.startswith("module "):
            module_path = value.split(None, 1)[1].strip()
            index.go_modules[project.name] = (module_path, relative)
            continue
        if value == "require (":
            in_require = True
            continue
        if in_require and value == ")":
            in_require = False
            continue
        if value.startswith("require "):
            value = value.split(None, 1)[1]
        elif not in_require:
            continue
        parts = value.split()
        if len(parts) < 2:
            continue
        name, version = parts[0], parts[1]
        _add_package(
            project,
            relative,
            store,
            graph,
            index,
            ecosystem="go",
            name=name,
            version=version,
            line=line_number,
            lifecycle="runtime",
        )
    if module_path is None:
        graph.add_unknown(
            AtlasUnknown(
                code="manifest.go-module-missing",
                message=f"{relative} has no module directive.",
                project=project.name,
                path=relative,
                neededEvidence="Add or repair the Go module directive.",
            )
        )
