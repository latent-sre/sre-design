"""Contract tests for the durable codebase atlas and its Agent Skill.

The atlas is useful only while its structure and dependency snapshot match the repository. These
tests keep the seven output pages aligned with the seven skill templates, resolve local links, and
recompute the Python import graph so a package-boundary change forces an intentional atlas refresh.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".github" / "skills" / "sre-codebase-atlas"
TEMPLATES = SKILL / "templates"
ATLAS = ROOT / "docs" / "codebase-atlas"
GENERATED = ATLAS / "generated"
SOURCE_REVIEW = ROOT / "docs" / "CODEBASE-ATLAS.md"

PAGES = {
    "README.md",
    "STACK.md",
    "STRUCTURE.md",
    "ARCHITECTURE.md",
    "DEPENDENCIES.md",
    "OPERATIONS.md",
    "CONCERNS.md",
}
EVIDENCE_LABELS = {
    "MANIFEST_DECLARED",
    "STATIC_EXTRACTED",
    "STATIC_RESOLVED",
    "ENGINE_CONFIRMED",
    "RUNTIME_OBSERVED",
    "OPERATOR_CONFIRMED",
    "INFERRED",
    "UNKNOWN",
}
_LINK = re.compile(r"\]\(([^)]+)\)")


def _headings(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("#")
    }


def test_atlas_and_templates_have_the_exact_page_set():
    assert {p.name for p in ATLAS.glob("*.md")} == PAGES
    assert {p.name for p in TEMPLATES.glob("*.md")} == PAGES


def test_finished_pages_preserve_template_headings_and_have_no_placeholders():
    for name in sorted(PAGES):
        actual = ATLAS / name
        assert _headings(TEMPLATES / name) <= _headings(actual)
        text = actual.read_text(encoding="utf-8")
        assert "<!--" not in text, f"{name} still contains a template placeholder"


def test_atlas_local_links_resolve():
    for doc in [SOURCE_REVIEW, *sorted(ATLAS.glob("*.md"))]:
        for target in _LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            rel = target.split("#", 1)[0]
            assert (doc.parent / rel).exists(), f"{doc}: dangling link -> {target}"


def test_skill_declares_evidence_and_dependency_contracts():
    evidence = (SKILL / "references" / "evidence-model.md").read_text(encoding="utf-8")
    dependency = (SKILL / "references" / "dependency-analysis.md").read_text(encoding="utf-8")
    platforms = (SKILL / "references" / "dotnet-node.md").read_text(encoding="utf-8")
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    assert EVIDENCE_LABELS <= {label for label in EVIDENCE_LABELS if f"`{label}`" in evidence}
    assert "Ce / (Ca + Ce)" in dependency
    assert "strongly connected components" in dependency
    assert "import matrix" in dependency
    assert "grep" in dependency.lower()
    assert "secret values" in skill
    assert "Inspect implementation before intent" in skill
    assert "packages.lock.json" in platforms
    assert "ProjectGraph" in platforms
    assert "package-lock" in platforms
    assert "TypeScript" in platforms


def test_cartographer_agent_routes_to_the_atlas_skill():
    agent = (ROOT / ".github" / "agents" / "sre-codebase-cartographer.agent.md").read_text(
        encoding="utf-8"
    )
    assert "sre-codebase-atlas" in agent
    assert "dotnet-node.md" in agent
    assert "declared package" in agent


def test_atlas_is_routed_once_in_the_canonical_pipeline():
    pipeline = yaml.safe_load(
        (ROOT / ".github" / "skills" / "pipeline.yaml").read_text(encoding="utf-8")
    )
    routed = [
        name
        for skills in pipeline["phases"].values()
        for name in skills
        if name == "sre-codebase-atlas"
    ]
    assert routed == ["sre-codebase-atlas"]


def test_source_review_pins_all_four_external_inputs():
    text = SOURCE_REVIEW.read_text(encoding="utf-8")
    assert "be7a1cf" in text
    assert "aa8d778" in text
    assert "d163006" in text
    assert "mcpmarket.com/tools/skills/dependency-graph-analyzer" in text
    assert "75b3874" in text
    assert "dotnet/msbuild@6954378" in text


def _source_modules() -> list[tuple[Path, str, bool]]:
    src = ROOT / "src"
    records = []
    for path in sorted((src / "sre_kb").rglob("*.py")):
        parts = list(path.relative_to(src).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        records.append((path, ".".join(parts), is_package))
    return records


def _resolved_import(
    module: str,
    is_package: bool,
    node: ast.ImportFrom,
    imported_name: str,
    known: set[str],
) -> str | None:
    package = module if is_package else module.rpartition(".")[0]
    if node.level:
        base = importlib.util.resolve_name("." * node.level + (node.module or ""), package)
    else:
        base = node.module or ""
    candidate = f"{base}.{imported_name}" if base else imported_name
    if candidate in known:
        return candidate
    if base in known:
        return base
    while candidate and candidate not in known:
        candidate = candidate.rpartition(".")[0]
    return candidate or None


def _import_graph() -> tuple[set[str], set[tuple[str, str]]]:
    records = _source_modules()
    known = {module for _, module, _ in records}
    edges: set[tuple[str, str]] = set()
    for path, module, is_package in records:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[str | None] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                targets = [
                    _resolved_import(module, is_package, node, alias.name, known)
                    for alias in node.names
                ]
            edges.update(
                (module, target) for target in targets if target in known and target != module
            )
    return known, edges


def _sccs(nodes: set[str], edges: set[tuple[str, str]]) -> list[frozenset[str]]:
    adjacency = {node: [] for node in nodes}
    for source, target in edges:
        adjacency[source].append(target)

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[frozenset[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            component = set()
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == node:
                    break
            components.append(frozenset(component))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return components


def _package(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) > 1 else module


def test_documented_dependency_snapshot_matches_source():
    modules, file_edges = _import_graph()
    file_cycles = [component for component in _sccs(modules, file_edges) if len(component) > 1]

    packages = {_package(module) for module in modules}
    package_edges = {
        (_package(source), _package(target))
        for source, target in file_edges
        if _package(source) != _package(target)
    }
    package_cycles = {
        component for component in _sccs(packages, package_edges) if len(component) > 1
    }

    assert file_cycles == []
    generated = json.loads((GENERATED / "atlas.json").read_text(encoding="utf-8"))
    generated_modules = {
        node["annotations"]["module"]: node["id"]
        for node in generated["nodes"]
        if node["type"] == "module"
        and node.get("path", "").startswith("src/sre_kb/")
        and "module" in node.get("annotations", {})
    }
    id_to_module = {node_id: module for module, node_id in generated_modules.items()}
    generated_edges = {
        (id_to_module[edge["source"]], id_to_module[edge["target"]])
        for edge in generated["edges"]
        if edge["scope"] == "source"
        and edge["resolver"] == "python:ast"
        and edge["source"] in id_to_module
        and edge["target"] in id_to_module
    }
    assert set(generated_modules) == modules
    assert generated_edges == file_edges

    generated_group_cycles = {
        frozenset(member.rsplit(":", 1)[-1] for member in cycle["members"])
        for cycle in generated["metrics"]["cycles"]
        if cycle["granularity"] == "group"
    }
    assert generated_group_cycles == package_cycles

    dependency_page = (ATLAS / "DEPENDENCIES.md").read_text(encoding="utf-8")
    assert "generated/atlas.json" in dependency_page
    assert "generated/DEPENDENCY-SNAPSHOT.md" in dependency_page
    snapshot = (GENERATED / "DEPENDENCY-SNAPSHOT.md").read_text(encoding="utf-8")
    assert "## Cross-package import matrix" in snapshot
    assert "Loose" not in snapshot
    assert "Tangled" not in snapshot


def test_generated_call_and_operational_projections_are_wired():
    assert (GENERATED / "call-graph.md").is_file()
    assert (GENERATED / "call-graph.mmd").is_file()
    assert (GENERATED / "OPERATIONAL-SIGNALS.md").is_file()
    report = (GENERATED / "OPERATIONAL-SIGNALS.md").read_text(encoding="utf-8")
    assert "tests/" not in report
    readme = (ATLAS / "README.md").read_text(encoding="utf-8")
    assert "generated/call-graph.md" in readme
    assert "generated/OPERATIONAL-SIGNALS.md" in readme
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "call-graph" in skill
    assert "OPERATIONAL-SIGNALS.md" in skill
