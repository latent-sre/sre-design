"""The envelope schema is the keystone of a *validated* KB. These tests prove it
accepts a well-formed artifact, rejects malformed ones, and stays in lock-step with
the pydantic model used to scaffold artifacts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.models.envelope import Artifact, Evidence, GeneratedBy, Lines, Metadata
from sre_kb.validation import validate_doc

FIXTURES = Path(__file__).parent / "fixtures"


def test_good_artifact_passes() -> None:
    doc = yaml.safe_load((FIXTURES / "kb-good" / "flow-place-order.yaml").read_text())
    assert validate_doc(doc) == []


def test_bad_artifact_is_rejected() -> None:
    doc = yaml.safe_load((FIXTURES / "kb-bad" / "bad-status.yaml").read_text())
    errors = validate_doc(doc)
    blob = " ".join(errors).lower()
    assert errors, "invalid artifact should produce errors"
    assert "status" in blob  # bad enum value
    assert "spec" in blob  # missing required


def test_unknown_top_level_field_rejected() -> None:
    doc = {
        "apiVersion": "sre.kb/v1alpha1",
        "kind": "Flow",
        "metadata": {"name": "x"},
        "spec": {},
        "status": "verified",
        "bogus": 1,
    }
    assert any("bogus" in e or "Additional" in e for e in validate_doc(doc))


def test_bad_excerpt_hash_rejected() -> None:
    doc = yaml.safe_load((FIXTURES / "kb-good" / "flow-place-order.yaml").read_text())
    doc["evidence"][0]["excerptHash"] = "sha256:not-a-real-hash"
    assert any("excerptHash" in e for e in validate_doc(doc))


def test_model_built_artifact_validates() -> None:
    """An artifact constructed via the pydantic model must satisfy the JSON Schema —
    this keeps the model and schema from drifting apart."""
    art = Artifact(
        kind="ResiliencyPattern",
        metadata=Metadata(name="inventory-cb", service="order-service"),
        spec={"type": "circuit-breaker", "library": "resilience4j"},
        evidence=[
            Evidence(
                repo="git@forge:platform/order-service.git",
                commit="5f3e9c1a7b",
                path="src/main/java/com/acme/order/client/InventoryClient.java",
                lines=Lines(start=20, end=24),
                excerptHash="sha256:" + "0123456789abcdef" * 4,
                detector="java_spring.resiliency",
            )
        ],
        confidence=0.9,
        status="verified",
        provenanceMode="deterministic",
        generatedBy=GeneratedBy(tool="sre-kb", driver="engine"),
    )
    assert validate_doc(art.to_doc()) == []
