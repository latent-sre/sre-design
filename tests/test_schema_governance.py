"""§7.6 schema governance: per-kind allow-lists (additionalProperties:false), the `ownership`
classification, and the `unverifiedAgainstLive` flag for offline-uncheckable claims."""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.models.envelope import Artifact, Metadata
from sre_kb.pipeline import run as run_pipeline
from sre_kb.validation import validate_doc

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def _flow(spec_extra: dict | None = None) -> dict:
    spec = {"trigger": {"type": "http"}, "steps": []}
    spec.update(spec_extra or {})
    return {"apiVersion": "sre.kb/v1alpha1", "kind": "Flow",
            "metadata": {"name": "x"}, "spec": spec, "status": "verified"}


def test_per_kind_allowlist_rejects_unknown_spec_field() -> None:
    assert validate_doc(_flow()) == []                       # only enumerated fields -> valid
    errs = validate_doc(_flow({"bogusField": 1}))
    assert any("bogusField" in e or "Additional" in e for e in errs)


def test_ownership_is_a_validated_enum() -> None:
    doc = Artifact(kind="Flow", metadata=Metadata(name="x", ownership="platform"),
                   spec={"trigger": {"type": "http"}, "steps": []}, status="verified").to_doc()
    assert doc["metadata"]["ownership"] == "platform"
    assert validate_doc(doc) == []
    doc["metadata"]["ownership"] = "nobody"                  # off-enum
    assert any("ownership" in e or "nobody" in e for e in validate_doc(doc))


def test_unverified_against_live_flags_only_live_claims(tmp_path) -> None:
    r = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="g", to_stage="validate")
    docs = {}
    for p in (r.root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        docs[(d["kind"], d["metadata"]["name"])] = d

    assert docs[("SloSli", "create-order-latency")].get("unverifiedAgainstLive") is True
    assert docs[("Alert", "create-order-latency-burn-rate")].get("unverifiedAgainstLive") is True
    # a byte-grounded artifact carries no such flag
    flow = next(d for (k, _), d in docs.items() if k == "Flow")
    assert "unverifiedAgainstLive" not in flow


def test_api_version_triangle_is_lock_step():
    """One version, declared three ways: the registry's apiVersion, the envelope's const, and the
    schema directory name must agree — a future v1beta1 bump that misses one corner would let
    artifacts claim a version their schemas don't implement."""
    import json

    import yaml

    from sre_kb.config import registry_path, schemas_dir

    registry = yaml.safe_load(registry_path().read_text())
    envelope = json.loads((schemas_dir() / "_envelope.schema.json").read_text())
    declared = registry["apiVersion"]                       # sre.kb/v1alpha1
    assert envelope["properties"]["apiVersion"]["const"] == declared
    version_dir = declared.split("/", 1)[1]                 # v1alpha1
    assert (schemas_dir() / version_dir).is_dir()
    assert all(version_dir in (row.get("schema") or "")     # every kind row points into that dir
               for row in registry["kinds"].values())
