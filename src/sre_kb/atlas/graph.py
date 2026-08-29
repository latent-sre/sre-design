"""Graph assembly primitives with stable IDs, evidence de-duplication, and raw metrics."""

from __future__ import annotations

import hashlib
from collections import defaultdict

from sre_kb.atlas.model import (
    AtlasEdge,
    AtlasEvidence,
    AtlasNode,
    AtlasSignal,
    AtlasUnknown,
    CouplingMetric,
    CycleMetric,
)


def stable_id(prefix: str, *parts: str) -> str:
    material = "\0".join(parts)
    short = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{short}"


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, AtlasNode] = {}
        self.edges: dict[tuple[str, str, str, str, str], AtlasEdge] = {}
        self.signals: dict[str, AtlasSignal] = {}
        self.unknowns: dict[tuple[str, str | None, str | None], AtlasUnknown] = {}

    def add_node(self, node: AtlasNode) -> AtlasNode:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        existing.evidence = _merge_evidence(existing.evidence, node.evidence)
        existing.licenses = sorted(set(existing.licenses) | set(node.licenses))
        existing.owners = sorted(set(existing.owners) | set(node.owners))
        for key, value in node.annotations.items():
            if isinstance(value, list) and isinstance(existing.annotations.get(key), list):
                existing.annotations[key] = sorted(
                    set(existing.annotations[key]) | set(value)
                )
            else:
                existing.annotations[key] = value
        if existing.version is None:
            existing.version = node.version
        if existing.coverage is None:
            existing.coverage = node.coverage
        if existing.changes is None:
            existing.changes = node.changes
        return existing

    def add_edge(
        self,
        source: str,
        target: str,
        *,
        kind: str,
        scope: str,
        resolver: str,
        evidence: list[AtlasEvidence],
        unresolved: bool = False,
        annotations: dict | None = None,
    ) -> AtlasEdge:
        key = (source, target, kind, scope, resolver)
        existing = self.edges.get(key)
        if existing is not None:
            existing.evidence = _merge_evidence(existing.evidence, evidence)
            existing.unresolved = existing.unresolved or unresolved
            for name, value in (annotations or {}).items():
                if isinstance(value, list) and isinstance(existing.annotations.get(name), list):
                    existing.annotations[name] = sorted(
                        set(existing.annotations[name]) | set(value)
                    )
                else:
                    existing.annotations[name] = value
            return existing
        edge = AtlasEdge(
            id=stable_id("edge", *key),
            source=source,
            target=target,
            kind=kind,
            scope=scope,
            resolver=resolver,
            unresolved=unresolved,
            annotations=annotations or {},
            evidence=evidence,
        )
        self.edges[key] = edge
        return edge

    def add_unknown(self, unknown: AtlasUnknown) -> None:
        key = (unknown.code, unknown.project, unknown.path)
        existing = self.unknowns.get(key)
        if existing is None:
            self.unknowns[key] = unknown
            return
        existing.evidence = _merge_evidence(existing.evidence, unknown.evidence)

    def add_signal(self, signal: AtlasSignal) -> None:
        self.signals.setdefault(signal.id, signal)


def _merge_evidence(
    left: list[AtlasEvidence],
    right: list[AtlasEvidence],
) -> list[AtlasEvidence]:
    by_key = {
        (
            evidence.evidenceClass,
            evidence.detector,
            evidence.path,
            evidence.lines.start if evidence.lines else None,
            evidence.lines.end if evidence.lines else None,
            evidence.source,
            evidence.observedAt,
            evidence.environment,
        ): evidence
        for evidence in [*left, *right]
    }
    return [
        by_key[key]
        for key in sorted(
            by_key,
            key=lambda item: tuple("" if value is None else str(value) for value in item),
        )
    ]


def coupling_and_cycles(
    nodes: list[AtlasNode],
    edges: list[AtlasEdge],
    *,
    scope: str = "source",
    granularity: str = "module",
    kinds: frozenset[str] = frozenset({"imports"}),
) -> tuple[list[CouplingMetric], list[CycleMetric]]:
    """Compute metrics over one explicitly named evidence scope and relationship kind."""
    selected = [
        edge
        for edge in edges
        if edge.scope == scope and edge.kind in kinds and not edge.unresolved
    ]
    node_by_id = {node.id: node for node in nodes}

    def metric_node(node_id: str) -> str:
        if granularity == "module":
            return node_id
        node = node_by_id[node_id]
        return f"group:{node.project or '?'}:{node.group or node.name}"

    node_ids = {
        metric_node(endpoint)
        for edge in selected
        for endpoint in (edge.source, edge.target)
        if endpoint in node_by_id
    }
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in selected:
        if edge.source not in node_by_id or edge.target not in node_by_id:
            continue
        source = metric_node(edge.source)
        target = metric_node(edge.target)
        if source in node_ids and target in node_ids and source != target:
            adjacency[source].add(target)
            incoming[target].add(source)

    coupling: list[CouplingMetric] = []
    for node_id in sorted(node_ids):
        ca = len(incoming[node_id])
        ce = len(adjacency[node_id])
        denominator = ca + ce
        if denominator:
            coupling.append(
                CouplingMetric(
                    node=node_id,
                    scope=scope,
                    granularity=granularity,
                    afferent=ca,
                    efferent=ce,
                    instability=round(ce / denominator, 6),
                )
            )

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node_id: str) -> None:
        nonlocal index
        indices[node_id] = lowlinks[node_id] = index
        index += 1
        stack.append(node_id)
        on_stack.add(node_id)
        for target in sorted(adjacency[node_id]):
            if target not in indices:
                visit(target)
                lowlinks[node_id] = min(lowlinks[node_id], lowlinks[target])
            elif target in on_stack:
                lowlinks[node_id] = min(lowlinks[node_id], indices[target])
        if lowlinks[node_id] == indices[node_id]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.append(member)
                if member == node_id:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node_id in sorted(node_ids):
        if node_id not in indices:
            visit(node_id)
    cycles = [
        CycleMetric(scope=scope, granularity=granularity, members=members)
        for members in sorted(components, key=lambda value: tuple(value))
    ]
    return coupling, cycles
