"""Atlas orchestration and deterministic drift checking."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sre_kb.atlas.config import AtlasConfig, AtlasConfigError, load_config, resolve_local_path
from sre_kb.atlas.evidence import EvidenceStore
from sre_kb.atlas.graph import Graph, coupling_and_cycles
from sre_kb.atlas.manifests import collect_manifests
from sre_kb.atlas.model import (
    AtlasMetadata,
    AtlasMetrics,
    AtlasNode,
    AtlasProject,
    AtlasSnapshot,
    EvidenceClass,
    LicenseRecord,
    NodeType,
)
from sre_kb.atlas.overlays import apply_overlays, project_license
from sre_kb.atlas.render import render_files
from sre_kb.atlas.source import collect_source


@dataclass(frozen=True)
class AtlasDrift:
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()

    @property
    def drifted(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def as_dict(self) -> dict[str, object]:
        return {
            "apiVersion": "sre.kb/atlas-drift/v1alpha1",
            "drifted": self.drifted,
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
        }


def build_atlas(
    target: Path | str,
    *,
    config_path: Path | None = None,
    include_history: bool | None = None,
) -> tuple[AtlasSnapshot, AtlasConfig]:
    root = Path(target).resolve()
    if not root.is_dir():
        raise AtlasConfigError(f"atlas target is not a directory: {root}")
    config, resolved_config, config_digest = load_config(root, config_path)
    store = EvidenceStore(root)
    graph = Graph()
    config_relative = resolved_config.relative_to(root).as_posix()
    config_lines = store.lines(config_relative)
    config_evidence = store.evidence(
        config_relative,
        1,
        max(1, len(config_lines)),
        "atlas.config.boundary",
        EvidenceClass.manifest_declared,
    )
    for project in config.projects:
        graph.add_node(
            AtlasNode(
                id=f"project:{project.name}",
                type=NodeType.project,
                name=project.name,
                project=project.name,
                group=project.name,
                annotations={
                    "roots": project.roots,
                    "testRoots": project.testRoots,
                    "manifests": project.manifests,
                },
                evidence=[config_evidence],
            )
        )
    manifests = collect_manifests(root, config, store, graph)
    collect_source(root, config, store, graph, manifests)
    apply_overlays(
        root,
        config,
        store,
        graph,
        manifests,
        include_history=include_history,
    )

    nodes = sorted(graph.nodes.values(), key=lambda node: node.id)
    edges = sorted(graph.edges.values(), key=lambda edge: edge.id)
    for node in nodes:
        node.evidence.sort(key=_evidence_sort_key)
        node.licenses = sorted(set(node.licenses))
        node.owners = sorted(set(node.owners))
    for edge in edges:
        edge.evidence.sort(key=_evidence_sort_key)
    module_coupling, module_cycles = coupling_and_cycles(nodes, edges)
    group_coupling, group_cycles = coupling_and_cycles(
        nodes,
        edges,
        granularity="group",
    )
    license_records = _license_inventory(nodes, manifests.licenses)
    project_license_value, project_license_source = project_license(root, manifests)
    snapshot = AtlasSnapshot(
        metadata=AtlasMetadata(
            repository=root.name,
            configPath=config_relative,
            configDigest=config_digest,
            treeDigest=store.tree_digest(),
            projectLicense=project_license_value,
            projectLicenseSource=project_license_source,
        ),
        projects=[
            AtlasProject(
                name=project.name,
                roots=project.roots,
                testRoots=project.testRoots,
                manifests=project.manifests,
            )
            for project in config.projects
        ],
        nodes=nodes,
        edges=edges,
        unknowns=sorted(
            graph.unknowns.values(),
            key=lambda unknown: (
                unknown.code,
                unknown.project or "",
                unknown.path or "",
            ),
        ),
        metrics=AtlasMetrics(
            coupling=[*module_coupling, *group_coupling],
            cycles=[*module_cycles, *group_cycles],
        ),
        licenses=license_records,
    )
    return snapshot, config


def _evidence_sort_key(evidence) -> tuple[str, ...]:
    return (
        str(evidence.evidenceClass),
        evidence.detector,
        evidence.path or "",
        str(evidence.lines.start if evidence.lines else 0),
        str(evidence.lines.end if evidence.lines else 0),
        evidence.source or "",
    )


def _license_inventory(
    nodes: list[AtlasNode],
    imported: list[LicenseRecord],
) -> list[LicenseRecord]:
    records = {record.node: record for record in imported}
    for node in nodes:
        if node.type != NodeType.package or node.group == "python-stdlib":
            continue
        records.setdefault(
            node.id,
            LicenseRecord(
                node=node.id,
                name=node.name,
                version=node.version,
                versions=[
                    str(value)
                    for value in node.annotations.get("declaredVersions", [])
                ]
                if isinstance(node.annotations.get("declaredVersions"), list)
                else ([node.version] if node.version else []),
                licenses=node.licenses,
                status="DECLARED" if node.licenses else "UNKNOWN",
                source=(
                    node.evidence[0].path
                    if node.evidence and node.evidence[0].path
                    else "source-import"
                ),
            ),
        )
    return sorted(records.values(), key=lambda item: (item.name.lower(), item.version or "", item.node))


def write_atlas(
    target: Path | str,
    *,
    config_path: Path | None = None,
    output: Path | None = None,
    include_history: bool | None = None,
) -> tuple[AtlasSnapshot, Path]:
    root = Path(target).resolve()
    snapshot, config = build_atlas(
        root,
        config_path=config_path,
        include_history=include_history,
    )
    output_path = _output_path(root, config.output.path, output)
    output_path.mkdir(parents=True, exist_ok=True)
    files = render_files(
        snapshot,
        max_diagram_nodes=config.output.maxDiagramNodes,
        include_html=config.output.html,
    )
    prior_names = _prior_generated_names(output_path)
    for stale in sorted(prior_names - set(files)):
        raw = output_path / stale
        resolved = raw.resolve()
        if (
            resolved.is_relative_to(output_path.resolve())
            and raw.is_file()
            and not raw.is_symlink()
        ):
            raw.unlink()
    for relative, content in sorted(files.items()):
        target_file = output_path / relative
        if target_file.is_symlink() or getattr(target_file, "is_junction", lambda: False)():
            raise AtlasConfigError(f"refusing to overwrite linked atlas output: {target_file}")
        target_file.write_text(content, encoding="utf-8", newline="\n")
    return snapshot, output_path


def check_atlas(
    target: Path | str,
    *,
    config_path: Path | None = None,
    output: Path | None = None,
    include_history: bool | None = None,
    report: Path | None = None,
) -> AtlasDrift:
    root = Path(target).resolve()
    snapshot, config = build_atlas(
        root,
        config_path=config_path,
        include_history=include_history,
    )
    output_path = _output_path(root, config.output.path, output)
    expected = render_files(
        snapshot,
        max_diagram_nodes=config.output.maxDiagramNodes,
        include_html=config.output.html,
    )
    actual_names = (
        {
            path.relative_to(output_path).as_posix()
            for path in output_path.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        if output_path.is_dir()
        else set()
    )
    expected_names = set(expected)
    added = tuple(sorted(expected_names - actual_names))
    removed = tuple(sorted(actual_names - expected_names))
    changed = tuple(
        sorted(
            name
            for name in expected_names & actual_names
            if (output_path / name).read_text(encoding="utf-8", errors="replace") != expected[name]
        )
    )
    drift = AtlasDrift(added=added, removed=removed, changed=changed)
    if report is not None:
        report_path = report if report.is_absolute() else root / report
        report_path = report_path.resolve()
        if not report_path.is_relative_to(root):
            raise AtlasConfigError("atlas drift report must remain inside the target repository")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(drift.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return drift


def _output_path(root: Path, configured: str, override: Path | None) -> Path:
    if override is None:
        return resolve_local_path(root, configured)
    if override.is_absolute():
        resolved = override.resolve()
        if not resolved.is_relative_to(root):
            raise AtlasConfigError("atlas output must remain inside the target repository")
        return resolved
    return resolve_local_path(root, override.as_posix())


def _prior_generated_names(output: Path) -> set[str]:
    manifest = output / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        return set()
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return set()
    names: set[str] = set()
    for value in files:
        candidate = Path(str(value))
        if not candidate.is_absolute() and ".." not in candidate.parts:
            names.add(candidate.as_posix())
    return names
