"""Versioned machine contract for the codebase atlas and imported evidence overlays."""

from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceClass(StrEnum):
    manifest_declared = "MANIFEST_DECLARED"
    static_extracted = "STATIC_EXTRACTED"
    static_resolved = "STATIC_RESOLVED"
    engine_confirmed = "ENGINE_CONFIRMED"
    runtime_observed = "RUNTIME_OBSERVED"
    operator_confirmed = "OPERATOR_CONFIRMED"
    inferred = "INFERRED"
    unknown = "UNKNOWN"


class AtlasLines(_Strict):
    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self) -> AtlasLines:
        if self.end < self.start:
            raise ValueError("line range end must be greater than or equal to start")
        return self


class AtlasEvidence(_Strict):
    evidenceClass: EvidenceClass
    detector: str = Field(min_length=1)
    path: str | None = None
    lines: AtlasLines | None = None
    excerptHash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    source: str | None = None
    observedAt: str | None = None
    environment: str | None = None

    @field_validator("path")
    @classmethod
    def repository_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        posix = PurePosixPath(value.replace("\\", "/"))
        windows = PureWindowsPath(value)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or bool(windows.drive)
            or ".." in posix.parts
        ):
            raise ValueError("evidence path must be repository-relative and contained")
        return posix.as_posix()

    @model_validator(mode="after")
    def evidence_shape_matches_class(self) -> AtlasEvidence:
        file_backed = {
            EvidenceClass.manifest_declared,
            EvidenceClass.static_extracted,
            EvidenceClass.static_resolved,
            EvidenceClass.engine_confirmed,
        }
        if self.evidenceClass in file_backed:
            if not (self.path and self.lines and self.excerptHash):
                raise ValueError(f"{self.evidenceClass} evidence requires path, lines, and excerptHash")
        if self.evidenceClass in {
            EvidenceClass.runtime_observed,
            EvidenceClass.operator_confirmed,
        } and not self.source:
            raise ValueError(f"{self.evidenceClass} evidence requires a named source")
        return self


class NodeType(StrEnum):
    project = "project"
    module = "module"
    test = "test"
    operational_file = "operational-file"
    package = "package"
    namespace = "namespace"
    service = "service"
    datastore = "datastore"
    queue = "queue"
    endpoint = "endpoint"
    unknown = "unknown"


AnnotationValue = Annotated[
    str | int | float | bool | None | list[str],
    Field(union_mode="left_to_right"),
]


class AtlasNode(_Strict):
    id: str = Field(min_length=1)
    type: NodeType
    name: str = Field(min_length=1)
    project: str | None = None
    path: str | None = None
    language: str | None = None
    group: str | None = None
    version: str | None = None
    licenses: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    changes: int | None = Field(default=None, ge=0)
    annotations: dict[str, AnnotationValue] = Field(default_factory=dict)
    evidence: list[AtlasEvidence] = Field(default_factory=list)


class AtlasEdge(_Strict):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    resolver: str = Field(min_length=1)
    unresolved: bool = False
    annotations: dict[str, AnnotationValue] = Field(default_factory=dict)
    evidence: list[AtlasEvidence] = Field(default_factory=list)


class AtlasUnknown(_Strict):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    project: str | None = None
    path: str | None = None
    neededEvidence: str = Field(min_length=1)
    evidence: list[AtlasEvidence] = Field(default_factory=list)


class AtlasSignal(_Strict):
    id: str = Field(min_length=1)
    node: str = Field(min_length=1)
    category: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    language: str = Field(min_length=1)
    path: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=1_000)
    annotations: dict[str, AnnotationValue] = Field(default_factory=dict)
    evidence: AtlasEvidence


class AtlasProject(_Strict):
    name: str = Field(min_length=1)
    roots: list[str]
    testRoots: list[str] = Field(default_factory=list)
    operationalRoots: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)


class CouplingMetric(_Strict):
    node: str
    scope: str
    granularity: str
    afferent: int = Field(ge=0)
    efferent: int = Field(ge=0)
    instability: float | None = Field(default=None, ge=0.0, le=1.0)


class CycleMetric(_Strict):
    scope: str
    granularity: str
    members: list[str] = Field(min_length=2)


class AtlasMetrics(_Strict):
    coupling: list[CouplingMetric] = Field(default_factory=list)
    cycles: list[CycleMetric] = Field(default_factory=list)


class LicenseRecord(_Strict):
    node: str
    name: str
    version: str | None = None
    versions: list[str] = Field(default_factory=list)
    licenses: list[str] = Field(default_factory=list)
    status: str
    source: str


class AtlasMetadata(_Strict):
    repository: str
    configPath: str
    configDigest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    treeDigest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    projectLicense: str = "UNKNOWN"
    projectLicenseSource: str | None = None


class AtlasSnapshot(_Strict):
    apiVersion: Literal["sre.kb/atlas/v1alpha1"] = "sre.kb/atlas/v1alpha1"
    kind: Literal["CodebaseAtlas"] = "CodebaseAtlas"
    metadata: AtlasMetadata
    projects: list[AtlasProject]
    nodes: list[AtlasNode]
    edges: list[AtlasEdge]
    signals: list[AtlasSignal] = Field(default_factory=list)
    unknowns: list[AtlasUnknown] = Field(default_factory=list)
    metrics: AtlasMetrics = Field(default_factory=AtlasMetrics)
    licenses: list[LicenseRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def graph_integrity(self) -> AtlasSnapshot:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("atlas node IDs must be unique")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("atlas edge IDs must be unique")
        known = set(node_ids)
        dangling = [
            edge.id
            for edge in self.edges
            if edge.source not in known or edge.target not in known
        ]
        if dangling:
            raise ValueError(f"atlas edges reference missing nodes: {dangling[:5]}")
        dangling_signals = [signal.id for signal in self.signals if signal.node not in known]
        if dangling_signals:
            raise ValueError(
                f"atlas signals reference missing nodes: {dangling_signals[:5]}"
            )
        return self


class RuntimeNode(_Strict):
    id: str
    name: str
    type: NodeType = NodeType.service
    project: str | None = None


class RuntimeEdge(_Strict):
    source: str
    target: str
    kind: str
    sourceName: str
    observedAt: str
    environment: str
    evidenceRef: str | None = None


class RuntimeEvidence(_Strict):
    apiVersion: Literal["sre.kb/runtime-evidence/v1alpha1"] = (
        "sre.kb/runtime-evidence/v1alpha1"
    )
    kind: Literal["RuntimeEvidence"] = "RuntimeEvidence"
    nodes: list[RuntimeNode] = Field(default_factory=list)
    edges: list[RuntimeEdge] = Field(default_factory=list)
