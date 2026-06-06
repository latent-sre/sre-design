"""Pydantic mirror of the artifact envelope (_envelope.schema.json).

The JSON Schema is the source of truth for *validation*; these models give the engine
typed, ergonomic construction of artifacts during scaffolding. The two are kept in
lock-step by tests/test_envelope_schema.py (a model-built artifact must validate).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Status(str, Enum):
    verified = "verified"
    needs_review = "needs-review"
    rejected = "rejected"


class ProvenanceMode(str, Enum):
    deterministic = "deterministic"
    llm_asserted = "llm-asserted"


class Driver(str, Enum):
    engine = "engine"
    copilot = "copilot"


class Lines(_Strict):
    start: int = Field(ge=1)
    end: int = Field(ge=1)


class Evidence(_Strict):
    repo: str
    commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    path: str
    lines: Lines
    excerptHash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    detector: str
    # Trust tier of the collector that produced this evidence: "ast" (deterministic,
    # byte-grounded; Tier-A) or "llm" (LLM-proposed; Tier-B). Defaults to "ast" so all
    # existing deterministic collectors are unaffected.
    source_tier: str = "ast"


class CrossRef(_Strict):
    kind: str = Field(pattern=r"^[A-Z][A-Za-z0-9]+$")
    name: str
    relation: str


class GeneratedBy(_Strict):
    tool: str = "sre-kb"
    driver: Driver = Driver.engine
    toolVersion: str | None = None
    provider: str | None = None
    promptVersion: str | None = None
    generatedAt: str | None = None


class Ownership(str, Enum):
    app = "app"
    platform = "platform"
    shared = "shared"


class Metadata(_Strict):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    service: str | None = None
    owner: str | None = None
    domain: str | None = None
    # Who owns this artifact class (governance), distinct from `owner` (the team/person).
    ownership: Ownership | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class Artifact(_Strict):
    """Base envelope. Per-kind models will subclass with a typed `spec`."""

    apiVersion: str = "sre.kb/v1alpha1"
    kind: str = Field(pattern=r"^[A-Z][A-Za-z0-9]+$")
    metadata: Metadata
    spec: dict = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Status = Status.needs_review
    provenanceMode: ProvenanceMode | None = None
    crossRefs: list[CrossRef] = Field(default_factory=list)
    generatedBy: GeneratedBy | None = None
    # True for claims that cannot be checked offline (live SLO thresholds, live metrics) — they
    # keep a normal status but flag that byte-grounding alone can't fully confirm them (§7.6).
    unverifiedAgainstLive: bool | None = None

    def to_doc(self) -> dict:
        """Serialize to a plain dict suitable for YAML + schema validation."""
        return self.model_dump(mode="json", exclude_none=True)
