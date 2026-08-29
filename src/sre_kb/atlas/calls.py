"""Conservative cross-file call resolution for the source atlas.

Resolution stops at a repository module/package boundary. It never claims a runtime hop, virtual
dispatch target, reflection target, or ambiguous same-named type. Strong evidence means an import
or declared field type and a repository definition agree; otherwise the edge is omitted and a
material ambiguity is recorded explicitly.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from collections import defaultdict
from pathlib import PurePosixPath

from tree_sitter import Node

from sre_kb.atlas.evidence import EvidenceStore
from sre_kb.atlas.graph import Graph
from sre_kb.atlas.manifests import ManifestIndex
from sre_kb.atlas.model import AtlasUnknown, EvidenceClass
from sre_kb.parsing.code_model import Module, TypeDecl, parse, syntax_tree


def resolve_cross_file_calls(
    records, store: EvidenceStore, graph: Graph, manifests: ManifestIndex
) -> None:
    by_language: dict[str, list] = defaultdict(list)
    for record in records:
        by_language[record.language].append(record)
    _resolve_python_calls(by_language["python"], store, graph)
    _resolve_typed_calls("java", by_language["java"], store, graph)
    _resolve_typed_calls("csharp", by_language["csharp"], store, graph)
    _resolve_javascript_calls(
        [
            *by_language["javascript"],
            *by_language["typescript"],
            *by_language["tsx"],
        ],
        store,
        graph,
        manifests,
    )
    _resolve_go_calls(by_language["go"], store, graph, manifests)


def _add_call(
    record,
    target_id: str,
    line: int,
    method: str,
    receiver: str,
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
        f"atlas.calls.{record.language}",
        EvidenceClass.static_resolved,
    )
    graph.add_edge(
        record.node_id,
        target_id,
        kind="calls",
        scope="test" if record.is_test else "source",
        resolver=resolver,
        evidence=[evidence],
        annotations={
            "methods": [method] if method else [],
            "receivers": [receiver] if receiver else [],
        },
    )


def _ambiguity(
    record, line: int, language: str, target: str, store: EvidenceStore, graph: Graph
) -> None:
    graph.add_unknown(
        AtlasUnknown(
            code=f"resolver.{language}-ambiguous-call-target",
            message=(
                f"Call target {target!r} at {record.relative}:{line} matches multiple "
                "repository definitions."
            ),
            project=record.project,
            path=record.relative,
            neededEvidence=(
                "Add or resolve an explicit import/namespace, or provide compiler-resolved "
                "symbol evidence."
            ),
            evidence=[
                store.evidence(
                    record.relative,
                    line,
                    line,
                    f"atlas.calls.{language}-ambiguous",
                    EvidenceClass.unknown,
                )
            ],
        )
    )


# ---- Python -----------------------------------------------------------------


def _resolve_python_calls(records, store: EvidenceStore, graph: Graph) -> None:
    modules: dict[str, object] = {}
    package_flags: dict[str, bool] = {}
    trees: dict[str, ast.AST] = {}
    definitions: dict[str, set[str]] = {}
    for record in records:
        module, is_package = _python_module(record, store.root)
        if not module:
            continue
        modules[module] = record
        package_flags[module] = is_package
        try:
            tree = ast.parse(store.text(record.relative))
        except SyntaxError:
            continue  # the import resolver already records the syntax error
        trees[module] = tree
        definitions[module] = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef))
        }

    known = set(modules)
    for module, tree in sorted(trees.items()):
        record = modules[module]
        module_aliases: dict[str, str] = {}
        symbol_aliases: dict[str, tuple[str, str]] = {}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    target = _longest_python_module(alias.name, known)
                    if target:
                        module_aliases[alias.asname or alias.name.split(".", 1)[0]] = target
            elif isinstance(node, ast.ImportFrom):
                base = _python_from_base(
                    module,
                    package_flags[module],
                    node.module,
                    node.level,
                )
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    candidate = f"{base}.{alias.name}" if base else alias.name
                    if candidate in known:
                        module_aliases[local] = candidate
                    elif base in known and alias.name in definitions.get(base, set()):
                        symbol_aliases[local] = (base, alias.name)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in module_aliases
            ):
                target_module = module_aliases[node.func.value.id]
                if node.func.attr in definitions.get(target_module, set()):
                    _add_call(
                        record,
                        modules[target_module].node_id,
                        node.lineno,
                        node.func.attr,
                        node.func.value.id,
                        store,
                        graph,
                        resolver="python:ast-call",
                    )
            elif isinstance(node.func, ast.Name) and node.func.id in symbol_aliases:
                target_module, symbol = symbol_aliases[node.func.id]
                _add_call(
                    record,
                    modules[target_module].node_id,
                    node.lineno,
                    symbol,
                    node.func.id,
                    store,
                    graph,
                    resolver="python:ast-call",
                )


def _python_from_base(module: str, is_package: bool, imported: str | None, level: int) -> str:
    package = module if is_package else module.rpartition(".")[0]
    if level:
        try:
            return importlib.util.resolve_name(
                "." * level + (imported or ""),
                package,
            )
        except (ImportError, ValueError):
            return imported or ""
    return imported or ""


def _longest_python_module(value: str, known: set[str]) -> str | None:
    candidate = value
    while candidate:
        if candidate in known:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def _python_module(record, root) -> tuple[str, bool]:
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


# ---- Java and C# ------------------------------------------------------------


def _resolve_typed_calls(language: str, records, store: EvidenceStore, graph: Graph) -> None:
    if not records:
        return
    parsed: dict[str, Module] = {}
    by_simple: dict[str, list[tuple[object, TypeDecl]]] = defaultdict(list)
    by_fqn: dict[str, tuple[object, TypeDecl]] = {}
    for record in records:
        module = parse(language, store.text(record.relative))
        parsed[record.relative] = module
        for declaration in module.types:
            by_simple[declaration.name].append((record, declaration))
            fqn = ".".join(filter(None, [module.namespace, declaration.name]))
            by_fqn[fqn] = (record, declaration)

    for record in records:
        module = parsed[record.relative]
        imported_types, imported_namespaces = _typed_imports(
            language,
            record,
            store,
            by_fqn,
        )
        for declaration in module.types:
            for method in declaration.methods:
                for call in method.calls:
                    field_type = declaration.fields.get(call.receiver)
                    if not field_type:
                        continue
                    simple = _simple_type(field_type)
                    candidates: list[tuple[object, TypeDecl]]
                    if simple in imported_types:
                        candidates = [imported_types[simple]]
                    else:
                        same_namespace = by_fqn.get(
                            ".".join(filter(None, [module.namespace, simple]))
                        )
                        if same_namespace is not None:
                            candidates = [same_namespace]
                        else:
                            candidates = [
                                item
                                for item in by_simple.get(simple, [])
                                if not imported_namespaces
                                or parsed[item[0].relative].namespace in imported_namespaces
                            ]
                    candidates = [
                        item
                        for item in candidates
                        if call.method in {candidate.name for candidate in item[1].methods}
                    ]
                    if len(candidates) == 1:
                        target, _ = candidates[0]
                        _add_call(
                            record,
                            target.node_id,
                            call.line,
                            call.method,
                            call.receiver,
                            store,
                            graph,
                            resolver=f"{language}:tree-sitter-call",
                        )
                    elif len(candidates) > 1:
                        _ambiguity(
                            record,
                            call.line,
                            language,
                            field_type,
                            store,
                            graph,
                        )


def _typed_imports(
    language: str, record, store: EvidenceStore, by_fqn: dict[str, tuple[object, TypeDecl]]
):
    root, source = _tree(record, store)
    imported_types: dict[str, tuple[object, TypeDecl]] = {}
    namespaces: set[str] = set()
    if language == "java":
        for declaration in _walk(root, {"import_declaration"}):
            value = _text(declaration, source).strip().removeprefix("import").strip()
            value = value.removeprefix("static").strip().rstrip(";").strip()
            if value.endswith(".*"):
                namespaces.add(value[:-2])
            elif value in by_fqn:
                imported_types[value.rsplit(".", 1)[-1]] = by_fqn[value]
                namespaces.add(value.rpartition(".")[0])
    else:
        for directive in _walk(root, {"using_directive"}):
            value = _text(directive, source).strip().removeprefix("using").strip().rstrip(";")
            if "=" in value:
                value = value.split("=", 1)[1].strip()
            if value in by_fqn:
                imported_types[value.rsplit(".", 1)[-1]] = by_fqn[value]
            else:
                namespaces.add(value)
    return imported_types, namespaces


def _simple_type(value: str) -> str:
    without_generics = re.sub(r"<.*>", "", value)
    return re.split(r"[.\s]", without_generics.replace("[]", "").rstrip("?"))[-1]


# ---- JavaScript / TypeScript ------------------------------------------------


def _resolve_javascript_calls(
    records, store: EvidenceStore, graph: Graph, manifests: ManifestIndex
) -> None:
    by_path = {record.relative: record for record in records}
    for record in records:
        root, source = _tree(record, store)
        aliases: dict[str, object] = {}
        for statement in _walk(root, {"import_statement"}):
            source_node = statement.child_by_field_name("source")
            if source_node is None:
                continue
            specifier = _unquote(_text(source_node, source))
            mapped = _mapped_node_specifier(record, specifier, by_path, manifests)
            target = mapped[0] if mapped else None
            if target is None and specifier.startswith("."):
                base = _normalize_posix(PurePosixPath(record.relative).parent / specifier)
                target = _first_node_target(base, by_path) if base is not None else None
            if target is None:
                continue
            clause = next(
                (child for child in statement.named_children if child.type == "import_clause"),
                None,
            )
            if clause is None:
                continue
            for child in clause.named_children:
                if child.type == "identifier":
                    aliases[_text(child, source)] = target
                elif child.type == "namespace_import":
                    identifiers = list(_walk(child, {"identifier"}))
                    if identifiers:
                        aliases[_text(identifiers[-1], source)] = target
                elif child.type == "named_imports":
                    for spec in _walk(child, {"import_specifier"}):
                        identifiers = list(_walk(spec, {"identifier"}))
                        if identifiers:
                            aliases[_text(identifiers[-1], source)] = target

        for call in _walk(root, {"call_expression"}):
            function = call.child_by_field_name("function")
            if function is None:
                continue
            alias = ""
            method = ""
            if function.type == "member_expression":
                obj = function.child_by_field_name("object")
                prop = function.child_by_field_name("property")
                if obj is not None and obj.type == "identifier":
                    alias = _text(obj, source)
                    method = _text(prop, source) if prop is not None else ""
            elif function.type == "identifier":
                alias = _text(function, source)
                method = alias
            target = aliases.get(alias)
            if target is not None:
                _add_call(
                    record,
                    target.node_id,
                    call.start_point.row + 1,
                    method,
                    alias,
                    store,
                    graph,
                    resolver=f"{record.language}:tree-sitter-call",
                )


# ---- Go ---------------------------------------------------------------------


def _resolve_go_calls(
    records, store: EvidenceStore, graph: Graph, manifests: ManifestIndex
) -> None:
    local_packages: dict[str, str] = {}
    for record in records:
        module_info = manifests.go_modules.get(record.project)
        if not module_info:
            continue
        module_name, manifest_path = module_info
        module_dir = PurePosixPath(manifest_path).parent
        relative_dir = PurePosixPath(record.relative).parent
        try:
            within = relative_dir.relative_to(module_dir)
        except ValueError:
            continue
        import_path = "/".join(
            filter(
                None,
                [
                    module_name,
                    within.as_posix() if within.as_posix() != "." else "",
                ],
            )
        )
        local_packages[import_path] = f"namespace:go:{import_path}"

    for record in records:
        root, source = _tree(record, store)
        aliases: dict[str, str] = {}
        for spec in _walk(root, {"import_spec"}):
            path_node = spec.child_by_field_name("path")
            if path_node is None:
                continue
            imported = _unquote(_text(path_node, source))
            target_id = local_packages.get(imported)
            if target_id is None or target_id not in graph.nodes:
                continue
            name_node = spec.child_by_field_name("name")
            alias = (
                _text(name_node, source)
                if name_node is not None
                else imported.rstrip("/").rsplit("/", 1)[-1]
            )
            if alias not in {"_", "."}:
                aliases[alias] = target_id
        for call in _walk(root, {"call_expression"}):
            function = call.child_by_field_name("function")
            if function is None or function.type != "selector_expression":
                continue
            operand = function.child_by_field_name("operand")
            field = function.child_by_field_name("field")
            if operand is None or operand.type != "identifier":
                continue
            alias = _text(operand, source)
            target_id = aliases.get(alias)
            if target_id:
                _add_call(
                    record,
                    target_id,
                    call.start_point.row + 1,
                    _text(field, source) if field is not None else "",
                    alias,
                    store,
                    graph,
                    resolver="go:tree-sitter-call",
                )


# Local syntax/path helpers intentionally live here instead of importing atlas.source. The source
# orchestrator imports this resolver, and a reverse import would create a production module cycle.


def _tree(record, store: EvidenceStore) -> tuple[Node, bytes]:
    tree, source = syntax_tree(record.language, store.text(record.relative))
    return tree.root_node, source


def _walk(node: Node | None, types: set[str]):
    if node is None:
        return
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in types:
            yield current
        stack.extend(reversed(current.children))


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _mapped_node_specifier(record, specifier: str, records: dict, manifests: ManifestIndex):
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


def _first_node_target(base: PurePosixPath, records: dict):
    candidates = [base]
    if not base.suffix:
        extensions = (".js", ".mjs", ".cjs", ".ts", ".tsx")
        candidates.extend(base.with_suffix(ext) for ext in extensions)
        candidates.extend(base / f"index{ext}" for ext in extensions)
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
