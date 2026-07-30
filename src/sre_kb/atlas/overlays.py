"""Imported runtime, ownership, coverage, change-history, and CycloneDX overlays."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from pydantic import ValidationError

from sre_kb.atlas.config import AtlasConfig
from sre_kb.atlas.evidence import EvidenceStore, safe_xml_root
from sre_kb.atlas.graph import Graph
from sre_kb.atlas.manifests import ManifestIndex
from sre_kb.atlas.model import (
    AtlasEvidence,
    AtlasNode,
    AtlasUnknown,
    EvidenceClass,
    LicenseRecord,
    NodeType,
    RuntimeEvidence,
)


def apply_overlays(
    root: Path,
    config: AtlasConfig,
    store: EvidenceStore,
    graph: Graph,
    manifests: ManifestIndex,
    *,
    include_history: bool | None = None,
) -> None:
    for relative in config.overlays.runtimeEvidence:
        _runtime(relative, store, graph)
    for relative in config.overlays.sbom:
        _cyclonedx(relative, store, graph, manifests)
    for relative in config.overlays.coverage:
        _coverage(relative, store, graph)
    _codeowners(config.overlays.codeowners, store, graph)
    history_enabled = config.overlays.changeHistory if include_history is None else include_history
    if history_enabled:
        _change_history(root, config.overlays.maxHistoryCommits, graph)


def _missing_overlay(relative: str, kind: str, graph: Graph) -> None:
    graph.add_unknown(
        AtlasUnknown(
            code=f"overlay.{kind}-missing",
            message=f"Configured {kind} overlay does not exist: {relative}",
            path=relative,
            neededEvidence=f"Generate the {kind} evidence file or remove it from the atlas config.",
        )
    )


def _runtime(relative: str, store: EvidenceStore, graph: Graph) -> None:
    if not (store.root / relative).is_file():
        _missing_overlay(relative, "runtime", graph)
        return
    try:
        data = RuntimeEvidence.model_validate_json(store.text(relative))
    except (ValidationError, ValueError) as exc:
        graph.add_unknown(
            AtlasUnknown(
                code="overlay.runtime-invalid",
                message=f"Invalid runtime evidence {relative}: {str(exc)[:240]}",
                path=relative,
                neededEvidence="Export a sre.kb/runtime-evidence/v1alpha1 document.",
            )
        )
        return
    for node in data.nodes:
        evidence = AtlasEvidence(
            evidenceClass=EvidenceClass.operator_confirmed,
            detector="atlas.overlay.runtime",
            source=relative,
        )
        graph.add_node(
            AtlasNode(
                id=node.id,
                type=node.type,
                name=node.name,
                project=node.project,
                group="runtime",
                evidence=[evidence],
            )
        )
    for edge in data.edges:
        evidence = AtlasEvidence(
            evidenceClass=EvidenceClass.runtime_observed,
            detector="atlas.overlay.runtime",
            source=edge.sourceName,
            observedAt=edge.observedAt,
            environment=edge.environment,
        )
        for node_id in (edge.source, edge.target):
            if node_id not in graph.nodes:
                graph.add_node(
                    AtlasNode(
                        id=node_id,
                        type=NodeType.unknown,
                        name=node_id,
                        group="runtime-unmapped",
                        annotations={"unmappedRuntimeNode": True},
                        evidence=[evidence],
                    )
                )
        graph.add_edge(
            edge.source,
            edge.target,
            kind=edge.kind,
            scope="runtime",
            resolver="runtime-evidence:v1alpha1",
            evidence=[evidence],
            annotations={"evidenceRef": edge.evidenceRef},
        )


def _cyclonedx(
    relative: str,
    store: EvidenceStore,
    graph: Graph,
    manifests: ManifestIndex,
) -> None:
    if not (store.root / relative).is_file():
        _missing_overlay(relative, "sbom", graph)
        return
    try:
        data = json.loads(store.text(relative))
    except json.JSONDecodeError as exc:
        graph.add_unknown(
            AtlasUnknown(
                code="overlay.sbom-invalid-json",
                message=f"Invalid SBOM JSON {relative}: {exc}",
                path=relative,
                neededEvidence="Generate a valid CycloneDX JSON BOM.",
            )
        )
        return
    if not isinstance(data, dict) or data.get("bomFormat") != "CycloneDX":
        graph.add_unknown(
            AtlasUnknown(
                code="overlay.sbom-unsupported",
                message=f"{relative} is not a CycloneDX JSON BOM.",
                path=relative,
                neededEvidence="Provide CycloneDX JSON or add a format-specific SBOM adapter.",
            )
        )
        return

    component_ids: dict[str, str] = {}
    for component in _components(data.get("components")):
        name = component.get("name")
        if not isinstance(name, str) or not name:
            continue
        version = component.get("version")
        version_value = str(version) if version is not None else None
        bom_ref = component.get("bom-ref")
        ref = str(bom_ref) if bom_ref is not None else f"{name}@{version_value or '?'}"
        ecosystem, package_name = _purl_identity(component.get("purl"))
        existing = manifests.package(ecosystem, package_name) if ecosystem and package_name else None
        node_id = existing or f"package:cyclonedx:{hashlib.sha256(ref.encode()).hexdigest()[:20]}"
        licenses = _component_licenses(component)
        line = store.find_line(relative, json.dumps(name))
        evidence = store.evidence(
            relative,
            line,
            line,
            "atlas.overlay.cyclonedx",
            EvidenceClass.manifest_declared,
        )
        graph.add_node(
            AtlasNode(
                id=node_id,
                type=NodeType.package,
                name=name,
                group=ecosystem or "cyclonedx",
                version=version_value,
                licenses=licenses,
                annotations={
                    "bomRef": ref,
                    "purl": component.get("purl") if isinstance(component.get("purl"), str) else None,
                },
                evidence=[evidence],
            )
        )
        component_ids[ref] = node_id
        record = LicenseRecord(
            node=node_id,
            name=name,
            version=version_value,
            versions=[version_value] if version_value else [],
            licenses=licenses,
            status="DECLARED" if licenses else "UNKNOWN",
            source=relative,
        )
        manifests.licenses = [item for item in manifests.licenses if item.node != node_id]
        manifests.licenses.append(record)

    dependencies = data.get("dependencies") or []
    if isinstance(dependencies, list):
        for relationship in dependencies:
            if not isinstance(relationship, dict):
                continue
            source_ref = relationship.get("ref")
            targets = relationship.get("dependsOn") or []
            if not isinstance(source_ref, str) or not isinstance(targets, list):
                continue
            source_id = component_ids.get(source_ref)
            for target_ref in targets:
                if source_id is None or not isinstance(target_ref, str):
                    continue
                target_id = component_ids.get(target_ref)
                if target_id is None:
                    graph.add_unknown(
                        AtlasUnknown(
                            code="overlay.sbom-unmapped-ref",
                            message=f"CycloneDX dependency references unknown bom-ref {target_ref!r}.",
                            path=relative,
                            neededEvidence="Include the referenced component in the BOM.",
                        )
                    )
                    continue
                line = store.find_line(relative, json.dumps(source_ref))
                evidence = store.evidence(
                    relative,
                    line,
                    line,
                    "atlas.overlay.cyclonedx-dependency",
                    EvidenceClass.manifest_declared,
                )
                graph.add_edge(
                    source_id,
                    target_id,
                    kind="depends-on",
                    scope="sbom",
                    resolver="cyclonedx-json",
                    evidence=[evidence],
                )


def _components(value: object):
    if not isinstance(value, list):
        return
    stack = [item for item in reversed(value) if isinstance(item, dict)]
    while stack:
        component = stack.pop()
        yield component
        children = component.get("components")
        if isinstance(children, list):
            stack.extend(item for item in reversed(children) if isinstance(item, dict))


def _component_licenses(component: dict) -> list[str]:
    results: set[str] = set()
    licenses = component.get("licenses") or []
    if not isinstance(licenses, list):
        return []
    for choice in licenses:
        if not isinstance(choice, dict):
            continue
        expression = choice.get("expression")
        if isinstance(expression, str) and expression:
            results.add(expression)
        license_data = choice.get("license")
        if isinstance(license_data, dict):
            value = license_data.get("id") or license_data.get("name")
            if isinstance(value, str) and value:
                results.add(value)
    return sorted(results)


def _purl_identity(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, str) or not value.startswith("pkg:"):
        return None, None
    body = value[4:].split("?", 1)[0].split("#", 1)[0]
    package_type, separator, remainder = body.partition("/")
    if not separator:
        return None, None
    name_part = unquote(remainder.rsplit("@", 1)[0])
    ecosystem = {
        "pypi": "pypi",
        "npm": "npm",
        "maven": "maven",
        "nuget": "nuget",
        "golang": "go",
    }.get(package_type)
    if ecosystem == "maven" and "/" in name_part:
        name_part = name_part.replace("/", ":", 1)
    elif ecosystem == "npm" and name_part.startswith("@") and "/" in name_part:
        pass
    return ecosystem, name_part if ecosystem else None


def _coverage(relative: str, store: EvidenceStore, graph: Graph) -> None:
    if not (store.root / relative).is_file():
        _missing_overlay(relative, "coverage", graph)
        return
    try:
        root = safe_xml_root(store.text(relative))
    except (ET.ParseError, ValueError) as exc:
        graph.add_unknown(
            AtlasUnknown(
                code="overlay.coverage-invalid",
                message=f"Invalid coverage XML {relative}: {exc}",
                path=relative,
                neededEvidence="Generate Cobertura-compatible XML coverage.",
            )
        )
        return
    path_nodes = {
        node.path: node
        for node in graph.nodes.values()
        if node.path and node.type in {NodeType.module, NodeType.test}
    }
    for class_node in root.findall(".//class"):
        filename = (class_node.get("filename") or "").replace("\\", "/").lstrip("./")
        line_rate = class_node.get("line-rate")
        if not filename or line_rate is None:
            continue
        try:
            coverage = float(line_rate)
        except ValueError:
            continue
        candidates = [
            node
            for path, node in path_nodes.items()
            if path == filename or path.endswith("/" + filename)
        ]
        if len(candidates) == 1:
            candidates[0].coverage = max(0.0, min(1.0, coverage))
            candidates[0].annotations["coverageSource"] = relative
            line = store.find_line(relative, filename)
            candidates[0].evidence.append(
                store.evidence(
                    relative,
                    line,
                    line,
                    "atlas.overlay.cobertura",
                    EvidenceClass.manifest_declared,
                )
            )
        elif len(candidates) > 1:
            graph.add_unknown(
                AtlasUnknown(
                    code="overlay.coverage-ambiguous-path",
                    message=f"Coverage path {filename!r} maps to multiple source nodes.",
                    path=relative,
                    neededEvidence="Export repository-relative coverage filenames.",
                )
            )


def _codeowners(paths: list[str], store: EvidenceStore, graph: Graph) -> None:
    existing = next((relative for relative in paths if (store.root / relative).is_file()), None)
    if existing is None:
        if paths:
            graph.add_unknown(
                AtlasUnknown(
                    code="overlay.codeowners-missing",
                    message="No configured CODEOWNERS candidate exists in this repository.",
                    neededEvidence=(
                        "Add a reviewed CODEOWNERS file or remove the ownership overlay candidates."
                    ),
                )
            )
        return
    rules: list[tuple[str, list[str], int]] = []
    for line_number, raw in enumerate(store.lines(existing), start=1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if "\\ " in value:
            graph.add_unknown(
                AtlasUnknown(
                    code="overlay.codeowners-escaped-space",
                    message=f"CODEOWNERS escaped-space pattern at {existing}:{line_number} is unsupported.",
                    path=existing,
                    neededEvidence="Add a standards-complete CODEOWNERS matcher.",
                )
            )
            continue
        parts = value.split()
        if len(parts) < 2:
            continue
        rules.append((parts[0], parts[1:], line_number))
    for node in graph.nodes.values():
        if not node.path:
            continue
        matched: tuple[list[str], int] | None = None
        for pattern, owners, line in rules:
            if _codeowners_match(node.path, pattern):
                matched = (owners, line)
        if matched:
            owners, line = matched
            node.owners = sorted(set(node.owners) | set(owners))
            node.evidence.append(
                store.evidence(
                    existing,
                    line,
                    line,
                    "atlas.overlay.codeowners",
                    EvidenceClass.manifest_declared,
                )
            )


def _codeowners_match(path: str, raw_pattern: str) -> bool:
    pattern = raw_pattern.lstrip("/")
    if pattern.endswith("/"):
        pattern += "**"
    if "/" not in pattern:
        return any(fnmatch.fnmatchcase(part, pattern) for part in PurePosixPath(path).parts)
    return fnmatch.fnmatchcase(path, pattern) or PurePosixPath(path).match(pattern)


def _change_history(root: Path, max_commits: int, graph: Graph) -> None:
    git = shutil.which("git")
    if git is None:
        graph.add_unknown(
            AtlasUnknown(
                code="overlay.git-unavailable",
                message="Git change-frequency overlay was requested but git is unavailable.",
                neededEvidence="Run atlas with git available or disable changeHistory.",
            )
        )
        return
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable/argv, no shell
            [
                git,
                "-C",
                str(root.resolve()),
                "log",
                "--format=",
                "--name-only",
                "-z",
                f"--max-count={max_commits}",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        graph.add_unknown(
            AtlasUnknown(
                code="overlay.git-failed",
                message=f"Git change-frequency collection failed: {str(exc)[:200]}",
                neededEvidence="Run the fixed git-log query in a complete local checkout.",
            )
        )
        return
    counts = Counter(
        value.decode("utf-8", "replace").replace("\\", "/")
        for value in result.stdout.split(b"\0")
        if value
    )
    evidence = AtlasEvidence(
        evidenceClass=EvidenceClass.operator_confirmed,
        detector="atlas.overlay.git-history",
        source=f"git log --name-only --max-count={max_commits}",
    )
    for node in graph.nodes.values():
        if node.path and node.path in counts:
            node.changes = counts[node.path]
            node.evidence.append(evidence)


def project_license(
    root: Path,
    manifests: ManifestIndex,
) -> tuple[str, str | None]:
    declared = sorted(set(manifests.project_licenses))
    values = {value for value, _ in declared}
    if len(values) == 1:
        return next(iter(values)), ", ".join(source for _, source in declared)
    if len(values) > 1:
        return "CONFLICT", "; ".join(f"{value} ({source})" for value, source in declared)
    license_files = sorted(
        path.relative_to(root).as_posix()
        for path in root.glob("LICENSE*")
        if path.is_file() and not path.is_symlink()
    )
    if license_files:
        return "FILE_PRESENT_UNCLASSIFIED", ", ".join(license_files)
    return "UNKNOWN", None
