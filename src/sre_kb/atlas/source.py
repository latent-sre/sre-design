"""Language-aware source dependency resolvers.

Python uses the standard AST. Java, C#, JavaScript, TypeScript/TSX, and Go use the same tree-sitter
grammars as the deterministic collectors. Dynamic loading remains explicit unknown evidence.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

from tree_sitter import Node

from sre_kb.atlas.config import (
    AtlasConfig,
    AtlasConfigError,
    ProjectConfig,
    is_excluded,
    resolve_local_path,
)
from sre_kb.atlas.evidence import EvidenceStore, MAX_ATLAS_FILE_BYTES
from sre_kb.atlas.graph import Graph
from sre_kb.atlas.manifests import ManifestIndex
from sre_kb.atlas.model import AtlasNode, AtlasUnknown, EvidenceClass, NodeType
from sre_kb.parsing.code_model import syntax_tree

_LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".java": "java",
    ".cs": "csharp",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "tsx",
}


@dataclass(frozen=True)
class SourceRecord:
    project: str
    relative: str
    source_root: str
    is_test: bool
    language: str
    node_id: str


def collect_source(
    root: Path,
    config: AtlasConfig,
    store: EvidenceStore,
    graph: Graph,
    manifests: ManifestIndex,
) -> list[SourceRecord]:
    records = discover_source(root, config, store, graph)
    by_language: dict[str, list[SourceRecord]] = {}
    for record in records:
        by_language.setdefault(record.language, []).append(record)

    _resolve_python(by_language.get("python", []), store, graph)
    _resolve_java(by_language.get("java", []), store, graph)
    _resolve_csharp(by_language.get("csharp", []), store, graph)
    _resolve_javascript(
        [
            *by_language.get("javascript", []),
            *by_language.get("typescript", []),
            *by_language.get("tsx", []),
        ],
        store,
        graph,
        manifests,
    )
    _resolve_go(by_language.get("go", []), store, graph, manifests)
    return records


def discover_source(
    root: Path,
    config: AtlasConfig,
    store: EvidenceStore,
    graph: Graph,
) -> list[SourceRecord]:
    records: dict[str, SourceRecord] = {}
    for project in config.projects:
        for source_root, is_test in [
            *((value, False) for value in project.roots),
            *((value, True) for value in project.testRoots),
        ]:
            absolute = resolve_local_path(root, source_root, must_exist=True)
            if not absolute.is_dir():
                raise AtlasConfigError(f"configured source root is not a directory: {source_root}")
            for dirpath, dirnames, filenames in absolute.walk():
                dirnames[:] = [
                    name
                    for name in dirnames
                    if not is_excluded(
                        (dirpath / name).relative_to(root).as_posix(), config.exclude
                    )
                ]
                for filename in sorted(filenames):
                    path = dirpath / filename
                    relative = path.relative_to(root).as_posix()
                    if (
                        is_excluded(relative, config.exclude)
                        or path.is_symlink()
                        or not path.is_file()
                        or path.stat().st_size > MAX_ATLAS_FILE_BYTES
                    ):
                        continue
                    language = _LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
                    if language is None:
                        continue
                    node_id = f"{'test' if is_test else 'module'}:{project.name}:{relative}"
                    record = SourceRecord(
                        project=project.name,
                        relative=relative,
                        source_root=source_root,
                        is_test=is_test,
                        language=language,
                        node_id=node_id,
                    )
                    records.setdefault(relative, record)
                    evidence = store.evidence(
                        relative,
                        1,
                        1,
                        f"atlas.source.{language}",
                        EvidenceClass.static_extracted,
                    )
                    graph.add_node(
                        AtlasNode(
                            id=node_id,
                            type=NodeType.test if is_test else NodeType.module,
                            name=path.name,
                            project=project.name,
                            path=relative,
                            language=language,
                            group=_default_group(project, source_root, relative),
                            evidence=[evidence],
                        )
                    )
                    graph.add_edge(
                        f"project:{project.name}",
                        node_id,
                        kind="contains",
                        scope="structure",
                        resolver="atlas:scope",
                        evidence=[evidence],
                    )
    return [records[key] for key in sorted(records)]


def _default_group(project: ProjectConfig, source_root: str, relative: str) -> str:
    within = PurePosixPath(relative).relative_to(PurePosixPath(source_root))
    parts = within.parts[:-1]
    if not parts:
        return project.name
    return ".".join(parts[:2])


def _scope(record: SourceRecord) -> str:
    return "test" if record.is_test else "source"


def _resolve_python(records: list[SourceRecord], store: EvidenceStore, graph: Graph) -> None:
    module_by_name: dict[str, SourceRecord] = {}
    package_flags: dict[str, bool] = {}
    for record in records:
        module, is_package = _python_module(record, store.root)
        if module:
            module_by_name[module] = record
            package_flags[module] = is_package
            graph.nodes[record.node_id].group = ".".join(module.split(".")[:2])
            graph.nodes[record.node_id].annotations["module"] = module

    known = set(module_by_name)
    for module, record in sorted(module_by_name.items()):
        try:
            tree = ast.parse(store.text(record.relative))
        except SyntaxError as exc:
            line = exc.lineno or 1
            graph.add_unknown(
                AtlasUnknown(
                    code="resolver.python-syntax-error",
                    message=f"Python AST could not parse {record.relative}: {exc.msg}",
                    project=record.project,
                    path=record.relative,
                    neededEvidence="Correct the syntax or use a parser compatible with this source.",
                    evidence=[
                        store.evidence(
                            record.relative,
                            line,
                            line,
                            "atlas.source.python",
                            EvidenceClass.unknown,
                        )
                    ],
                )
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    _python_edge(
                        record,
                        alias.name,
                        node.lineno,
                        module_by_name,
                        store,
                        graph,
                    )
            elif isinstance(node, ast.ImportFrom):
                targets = _resolve_python_from(
                    module,
                    package_flags[module],
                    node,
                    known,
                )
                for target in targets:
                    _python_edge(
                        record,
                        target,
                        node.lineno,
                        module_by_name,
                        store,
                        graph,
                    )
            elif isinstance(node, ast.Call) and _is_dynamic_python_import(node):
                graph.add_unknown(
                    AtlasUnknown(
                        code="resolver.python-dynamic-import",
                        message=f"Dynamic Python import at {record.relative}:{node.lineno}.",
                        project=record.project,
                        path=record.relative,
                        neededEvidence="Provide runtime import evidence or a constant-aware resolver.",
                        evidence=[
                            store.evidence(
                                record.relative,
                                node.lineno,
                                getattr(node, "end_lineno", node.lineno),
                                "atlas.source.python-dynamic",
                                EvidenceClass.unknown,
                            )
                        ],
                    )
                )


def _python_module(record: SourceRecord, root: Path) -> tuple[str, bool]:
    source_root = root / record.source_root
    path = PurePosixPath(record.relative)
    within = path.relative_to(PurePosixPath(record.source_root)).with_suffix("")
    parts = list(within.parts)
    is_package = bool(parts and parts[-1] == "__init__")
    if is_package:
        parts.pop()
    if (source_root / "__init__.py").is_file():
        parts.insert(0, source_root.name)
    return ".".join(parts), is_package


def _resolve_python_from(
    module: str,
    is_package: bool,
    node: ast.ImportFrom,
    known: set[str],
) -> list[str]:
    package = module if is_package else module.rpartition(".")[0]
    if node.level:
        try:
            base = importlib.util.resolve_name(
                "." * node.level + (node.module or ""),
                package,
            )
        except (ImportError, ValueError):
            return [node.module or ""]
    else:
        base = node.module or ""
    resolved: list[str] = []
    for alias in node.names:
        candidate = f"{base}.{alias.name}" if base else alias.name
        if candidate in known:
            resolved.append(candidate)
        elif base in known:
            resolved.append(base)
        else:
            resolved.append(base or candidate)
    return sorted(set(filter(None, resolved)))


def _python_edge(
    record: SourceRecord,
    imported: str,
    line: int,
    modules: dict[str, SourceRecord],
    store: EvidenceStore,
    graph: Graph,
) -> None:
    candidate = imported
    while candidate and candidate not in modules:
        candidate = candidate.rpartition(".")[0]
    if candidate:
        target = modules[candidate]
        if target.node_id == record.node_id:
            return
        evidence_class = EvidenceClass.static_resolved
        target_id = target.node_id
        unresolved = False
        scope = _scope(record)
    else:
        top = imported.split(".", 1)[0]
        stdlib = top in sys.stdlib_module_names
        target_id = f"package:python-stdlib:{top}" if stdlib else f"import:python:{top}"
        evidence_class = EvidenceClass.static_extracted
        unresolved = not stdlib
        scope = "source-external"
        graph.add_node(
            AtlasNode(
                id=target_id,
                type=NodeType.package,
                name=top,
                group="python-stdlib" if stdlib else "python-import",
                annotations={"importName": imported, "importedBy": [record.project]},
                evidence=[
                    store.evidence(
                        record.relative,
                        line,
                        line,
                        "atlas.source.python-import",
                        evidence_class,
                    )
                ],
            )
        )
    evidence = store.evidence(
        record.relative,
        line,
        line,
        "atlas.source.python-import",
        evidence_class,
    )
    graph.add_edge(
        record.node_id,
        target_id,
        kind="imports",
        scope=scope,
        resolver="python:ast",
        evidence=[evidence],
        unresolved=unresolved,
    )


def _is_dynamic_python_import(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id == "__import__"
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return node.func.value.id == "importlib" and node.func.attr == "import_module"
    return False


def _tree(record: SourceRecord, store: EvidenceStore) -> tuple[Node, bytes]:
    tree, source = syntax_tree(record.language, store.text(record.relative))
    return tree.root_node, source


def _walk(node: Node, types: set[str]) -> Iterable[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            yield current
        stack.extend(reversed(current.children))


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _named_text(node: Node, source: bytes) -> str:
    named = [child for child in node.named_children]
    return _text(named[-1], source) if named else ""


def _resolve_java(records: list[SourceRecord], store: EvidenceStore, graph: Graph) -> None:
    symbols: dict[str, SourceRecord] = {}
    packages: dict[str, str] = {}
    parsed: dict[str, tuple[Node, bytes]] = {}
    for record in records:
        root, source = _tree(record, store)
        parsed[record.relative] = (root, source)
        package = ""
        declaration = next(_walk(root, {"package_declaration"}), None)
        if declaration is not None:
            package = _named_text(declaration, source).strip()
        graph.nodes[record.node_id].group = package or record.project
        graph.nodes[record.node_id].annotations["package"] = package
        packages.setdefault(package, f"namespace:java:{package or record.project}")
        for declaration in _walk(
            root,
            {
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "record_declaration",
            },
        ):
            name = declaration.child_by_field_name("name")
            if name is not None:
                fqn = ".".join(filter(None, [package, _text(name, source)]))
                symbols[fqn] = record
    for record in records:
        root, source = parsed[record.relative]
        for declaration in _walk(root, {"import_declaration"}):
            value = _text(declaration, source).strip().removeprefix("import").strip()
            value = value.removeprefix("static").strip().rstrip(";").strip()
            line = declaration.start_point.row + 1
            target = _longest_symbol_prefix(value.rstrip(".*"), symbols)
            if target is not None:
                _source_edge(
                    record,
                    symbols[target].node_id,
                    line,
                    store,
                    graph,
                    resolver="java:tree-sitter",
                )
                continue
            package = value[:-2] if value.endswith(".*") else value.rpartition(".")[0]
            if package in packages:
                target_id = _namespace_node(
                    graph,
                    "java",
                    package,
                    record.project,
                    store,
                    record.relative,
                    line,
                )
                _source_edge(
                    record,
                    target_id,
                    line,
                    store,
                    graph,
                    resolver="java:tree-sitter",
                )
            else:
                _external_edge(
                    record,
                    value,
                    line,
                    "java",
                    store,
                    graph,
                    resolver="java:tree-sitter",
                )


def _longest_symbol_prefix(value: str, symbols: dict[str, SourceRecord]) -> str | None:
    candidate = value
    while candidate:
        if candidate in symbols:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _resolve_csharp(records: list[SourceRecord], store: EvidenceStore, graph: Graph) -> None:
    namespaces: dict[str, str] = {}
    parsed: dict[str, tuple[Node, bytes]] = {}
    for record in records:
        root, source = _tree(record, store)
        parsed[record.relative] = (root, source)
        declaration = next(
            _walk(root, {"namespace_declaration", "file_scoped_namespace_declaration"}),
            None,
        )
        namespace = ""
        if declaration is not None:
            name = declaration.child_by_field_name("name")
            namespace = (
                _text(name, source) if name is not None else _named_text(declaration, source)
            )
        graph.nodes[record.node_id].group = namespace or record.project
        graph.nodes[record.node_id].annotations["namespace"] = namespace
        if namespace:
            namespaces[namespace] = _namespace_node(
                graph,
                "csharp",
                namespace,
                record.project,
                store,
                record.relative,
                declaration.start_point.row + 1 if declaration is not None else 1,
            )
    for record in records:
        root, source = parsed[record.relative]
        for directive in _walk(root, {"using_directive"}):
            value = _text(directive, source).strip().removeprefix("using").strip().rstrip(";")
            if "=" in value:
                value = value.split("=", 1)[1].strip()
            line = directive.start_point.row + 1
            target_namespace = next(
                (
                    namespace
                    for namespace in sorted(namespaces, key=len, reverse=True)
                    if value == namespace or value.startswith(namespace + ".")
                ),
                None,
            )
            if target_namespace:
                _source_edge(
                    record,
                    namespaces[target_namespace],
                    line,
                    store,
                    graph,
                    resolver="csharp:tree-sitter",
                )
            else:
                _external_edge(
                    record,
                    value,
                    line,
                    "nuget-namespace",
                    store,
                    graph,
                    resolver="csharp:tree-sitter",
                )


def _resolve_javascript(
    records: list[SourceRecord],
    store: EvidenceStore,
    graph: Graph,
    manifests: ManifestIndex,
) -> None:
    by_path = {record.relative: record for record in records}
    for record in records:
        root, source = _tree(record, store)
        graph.nodes[record.node_id].group = str(PurePosixPath(record.relative).parent)
        nodes = list(_walk(root, {"import_statement", "export_statement", "call_expression"}))
        for node in nodes:
            specifier: str | None = None
            dynamic_kind: str | None = None
            if node.type in {"import_statement", "export_statement"}:
                source_node = node.child_by_field_name("source")
                if source_node is not None:
                    specifier = _unquote(_text(source_node, source))
            else:
                function = node.child_by_field_name("function")
                function_name = _text(function, source) if function is not None else ""
                if function_name in {"require", "import"}:
                    dynamic_kind = function_name
                    arguments = node.child_by_field_name("arguments")
                    strings = list(_walk(arguments, {"string"})) if arguments is not None else []
                    if strings:
                        specifier = _unquote(_text(strings[0], source))
                    else:
                        graph.add_unknown(
                            AtlasUnknown(
                                code=f"resolver.{record.language}-dynamic-{function_name}",
                                message=(
                                    f"Dynamic {function_name}() at "
                                    f"{record.relative}:{node.start_point.row + 1}."
                                ),
                                project=record.project,
                                path=record.relative,
                                neededEvidence="Provide runtime module-load evidence.",
                                evidence=[
                                    store.evidence(
                                        record.relative,
                                        node.start_point.row + 1,
                                        node.end_point.row + 1,
                                        f"atlas.source.{record.language}-dynamic",
                                        EvidenceClass.unknown,
                                    )
                                ],
                            )
                        )
            if specifier:
                _javascript_specifier(
                    record,
                    specifier,
                    node.start_point.row + 1,
                    by_path,
                    store,
                    graph,
                    manifests,
                    dynamic=dynamic_kind is not None,
                )


def _unquote(value: str) -> str:
    return value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" else value


def _javascript_specifier(
    record: SourceRecord,
    specifier: str,
    line: int,
    records: dict[str, SourceRecord],
    store: EvidenceStore,
    graph: Graph,
    manifests: ManifestIndex,
    *,
    dynamic: bool = False,
) -> None:
    resolver_base = f"{record.language}:tree-sitter"
    mapped = _mapped_node_specifier(record, specifier, records, manifests)
    if mapped is not None:
        target, mapping = mapped
        _source_edge(
            record,
            target.node_id,
            line,
            store,
            graph,
            resolver=f"{resolver_base}+{mapping}",
        )
        return
    if specifier.startswith("."):
        parent = PurePosixPath(record.relative).parent
        base = _normalize_posix(parent / specifier)
        if base is None:
            _external_edge(
                record,
                specifier,
                line,
                "javascript-relative",
                store,
                graph,
                resolver=resolver_base,
            )
            return
        target = _first_node_target(base, records)
        if target:
            _source_edge(
                record,
                target.node_id,
                line,
                store,
                graph,
                resolver=resolver_base,
            )
            return
        _external_edge(
            record,
            specifier,
            line,
            "javascript-relative",
            store,
            graph,
            resolver=resolver_base,
        )
        return
    if specifier.startswith("node:"):
        builtin = specifier.removeprefix("node:")
        evidence = store.evidence(
            record.relative,
            line,
            line,
            f"atlas.source.{record.language}-node-builtin",
            EvidenceClass.static_resolved,
        )
        target_id = f"namespace:node:{builtin}"
        graph.add_node(
            AtlasNode(
                id=target_id,
                type=NodeType.namespace,
                name=specifier,
                language="javascript",
                group="node-builtin",
                evidence=[evidence],
            )
        )
        graph.add_edge(
            record.node_id,
            target_id,
            kind="dynamic-imports" if dynamic else "imports",
            scope="package-import",
            resolver=f"{resolver_base}+node-builtin",
            evidence=[evidence],
        )
        return
    package = (
        "/".join(specifier.split("/")[:2])
        if specifier.startswith("@")
        else specifier.split("/", 1)[0]
    )
    package_id = manifests.package("npm", package, record.project)
    if package_id:
        package_node = graph.nodes.get(package_id)
        resolved = package_node is not None and package_node.version is not None
        evidence = store.evidence(
            record.relative,
            line,
            line,
            f"atlas.source.{record.language}-import",
            EvidenceClass.static_resolved,
        )
        graph.add_edge(
            record.node_id,
            package_id,
            kind="dynamic-imports" if dynamic else "imports",
            scope="package-import",
            resolver=f"{resolver_base}+{'package-lock' if resolved else 'package-json'}",
            evidence=[evidence],
        )
    else:
        _external_edge(
            record,
            package,
            line,
            "npm",
            store,
            graph,
            resolver=resolver_base,
        )


def _mapped_node_specifier(
    record: SourceRecord,
    specifier: str,
    records: dict[str, SourceRecord],
    manifests: ManifestIndex,
) -> tuple[SourceRecord, str] | None:
    package_imports = manifests.node_imports.get(record.project, {})
    for pattern, target_pattern in sorted(package_imports.items()):
        mapped = _apply_path_mapping(pattern, target_pattern, specifier)
        if mapped is None:
            continue
        target = _first_node_target(PurePosixPath(mapped), records)
        if target is not None:
            return target, "package-imports"

    config = manifests.typescript_configs.get(record.project)
    if config is None or record.language not in {"typescript", "tsx"}:
        return None
    for pattern, targets in sorted(config.paths.items()):
        for target_pattern in targets:
            mapped = _apply_path_mapping(pattern, target_pattern, specifier)
            if mapped is None:
                continue
            base = _normalize_posix(PurePosixPath(config.base) / mapped)
            if base is None:
                continue
            target = _first_node_target(base, records)
            if target is not None:
                return target, "tsconfig"
    return None


def _apply_path_mapping(pattern: str, target: str, specifier: str) -> str | None:
    if "*" not in pattern:
        return target if pattern == specifier else None
    prefix, _, suffix = pattern.partition("*")
    if not specifier.startswith(prefix) or not specifier.endswith(suffix):
        return None
    middle_end = len(specifier) - len(suffix) if suffix else len(specifier)
    wildcard = specifier[len(prefix) : middle_end]
    return target.replace("*", wildcard)


def _first_node_target(
    base: PurePosixPath,
    records: dict[str, SourceRecord],
) -> SourceRecord | None:
    candidates = [base]
    if not base.suffix:
        candidates.extend(base.with_suffix(ext) for ext in (".js", ".mjs", ".cjs", ".ts", ".tsx"))
        candidates.extend(base / f"index{ext}" for ext in (".js", ".mjs", ".cjs", ".ts", ".tsx"))
    return next(
        (
            records[candidate.as_posix()]
            for candidate in candidates
            if candidate.as_posix() in records
        ),
        None,
    )


def _normalize_posix(path: PurePosixPath) -> PurePosixPath | None:
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


def _resolve_go(
    records: list[SourceRecord],
    store: EvidenceStore,
    graph: Graph,
    manifests: ManifestIndex,
) -> None:
    project_dirs: dict[str, dict[str, str]] = {}
    for record in records:
        module_info = manifests.go_modules.get(record.project)
        relative_dir = PurePosixPath(record.relative).parent
        graph.nodes[record.node_id].group = relative_dir.as_posix()
        if module_info:
            module_name, manifest_path = module_info
            module_dir = PurePosixPath(manifest_path).parent
            try:
                within = relative_dir.relative_to(module_dir)
            except ValueError:
                continue
            import_path = "/".join(
                filter(None, [module_name, within.as_posix() if within.as_posix() != "." else ""])
            )
            target_id = _namespace_node(
                graph,
                "go",
                import_path,
                record.project,
                store,
                record.relative,
                1,
            )
            project_dirs.setdefault(record.project, {})[import_path] = target_id
    for record in records:
        root, source = _tree(record, store)
        for spec in _walk(root, {"import_spec"}):
            path_node = spec.child_by_field_name("path")
            if path_node is None:
                continue
            imported = _unquote(_text(path_node, source))
            line = spec.start_point.row + 1
            local = project_dirs.get(record.project, {}).get(imported)
            if local:
                _source_edge(
                    record,
                    local,
                    line,
                    store,
                    graph,
                    resolver="go:tree-sitter+go-mod",
                )
                continue
            package_id = manifests.package("go", imported)
            if package_id:
                evidence = store.evidence(
                    record.relative,
                    line,
                    line,
                    "atlas.source.go-import",
                    EvidenceClass.static_resolved,
                )
                graph.add_edge(
                    record.node_id,
                    package_id,
                    kind="imports",
                    scope="package-import",
                    resolver="go:tree-sitter+go-mod",
                    evidence=[evidence],
                )
            else:
                _external_edge(
                    record,
                    imported,
                    line,
                    "go",
                    store,
                    graph,
                    resolver="go:tree-sitter",
                )


def _namespace_node(
    graph: Graph,
    language: str,
    name: str,
    project: str,
    store: EvidenceStore,
    relative: str,
    line: int,
) -> str:
    node_id = f"namespace:{language}:{name}"
    evidence = store.evidence(
        relative,
        line,
        line,
        f"atlas.source.{language}-namespace",
        EvidenceClass.static_resolved,
    )
    graph.add_node(
        AtlasNode(
            id=node_id,
            type=NodeType.namespace,
            name=name,
            project=project,
            language=language,
            group=name,
            evidence=[evidence],
        )
    )
    return node_id


def _source_edge(
    record: SourceRecord,
    target_id: str,
    line: int,
    store: EvidenceStore,
    graph: Graph,
    *,
    resolver: str,
) -> None:
    if target_id == record.node_id:
        return
    evidence = store.evidence(
        record.relative,
        line,
        line,
        f"atlas.source.{record.language}-import",
        EvidenceClass.static_resolved,
    )
    graph.add_edge(
        record.node_id,
        target_id,
        kind="imports",
        scope=_scope(record),
        resolver=resolver,
        evidence=[evidence],
    )


def _external_edge(
    record: SourceRecord,
    imported: str,
    line: int,
    ecosystem: str,
    store: EvidenceStore,
    graph: Graph,
    *,
    resolver: str,
) -> None:
    target_id = f"import:{ecosystem}:{imported}"
    evidence = store.evidence(
        record.relative,
        line,
        line,
        f"atlas.source.{record.language}-import",
        EvidenceClass.static_extracted,
    )
    graph.add_node(
        AtlasNode(
            id=target_id,
            type=NodeType.package,
            name=imported,
            group=f"{ecosystem}-import",
            annotations={"importName": imported, "importedBy": [record.project]},
            evidence=[evidence],
        )
    )
    graph.add_edge(
        record.node_id,
        target_id,
        kind="imports",
        scope="source-external",
        resolver=resolver,
        evidence=[evidence],
        unresolved=True,
    )
