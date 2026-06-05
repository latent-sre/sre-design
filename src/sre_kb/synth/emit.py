"""Shared artifact emitter used by the scaffolder and the P2 inventory builder."""

from __future__ import annotations

from sre_kb import __version__
from sre_kb.models.envelope import Artifact, CrossRef, Evidence, GeneratedBy, Metadata
from sre_kb.util import slug


def emit(
    kind: str,
    name: str,
    spec: dict,
    evidence: list[Evidence],
    status: str,
    confidence: float | None,
    service: str,
    cross_refs: list[dict] | None = None,
    provenance: str = "deterministic",
) -> dict:
    art = Artifact(
        kind=kind,
        metadata=Metadata(name=slug(name), service=service),
        spec=spec,
        evidence=evidence,
        confidence=confidence,
        status=status,
        provenanceMode=provenance,
        crossRefs=[CrossRef(**c) for c in (cross_refs or [])],
        generatedBy=GeneratedBy(tool="sre-kb", driver="engine", toolVersion=__version__),
    )
    return art.to_doc()
