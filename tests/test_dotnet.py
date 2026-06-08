"""Repo-neutrality: a .NET/Steeltoe service yields the SAME kinds through the SAME
pipeline (new collectors emit the same normalized facts; scaffold/validate unchanged)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.validation import validate_kb_tree

FIXTURE = Path(__file__).parent / "fixtures" / "sample-dotnet-steeltoe"


@pytest.fixture(scope="module")
def kb(tmp_path_factory):
    work = tmp_path_factory.mktemp("w")
    r = run_pipeline(str(FIXTURE), work_root=str(work), run_id="net", to_stage="validate")
    docs = {}
    for p in (r.root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        docs[(d["kind"], d["metadata"]["name"])] = d
    return docs, r


def test_kb_validates(kb):
    _, r = kb
    bad = [x for x in validate_kb_tree(r.root / "kb") if not x.ok]
    assert not bad, [(x.path, x.errors) for x in bad]


def test_flow_from_csharp(kb):
    docs, _ = kb
    flow = docs[("Flow", "create-order")]
    assert flow["status"] == "verified"
    names = [s["name"] for s in flow["spec"]["steps"]]
    assert any("reserve" in n for n in names)
    assert any("persist" in n for n in names)
    pub = next(s for s in flow["spec"]["steps"] if "publish" in s["name"])
    assert any(fm.get("dataLossRisk") for fm in pub["failureModes"])


def test_csharp_swallow_level_is_normalized_like_java():
    """swallowed.failure `level` must be consistent across stacks — C# `LogError` and slf4j `error`
    both normalize to `error` (lowercase, no `log` prefix)."""
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.dotnet_steeltoe import annotations
    from sre_kb.util import swallow_level

    assert swallow_level("LogError") == "error" == swallow_level("error")

    ctx = ScanContext(root=FIXTURE, repo="file://x")
    swallows = [f for f in annotations.collect(ctx) if f.type == "swallowed.failure"]
    assert swallows
    for f in swallows:
        level = f.attrs["level"]
        assert level == level.lower() and not level.startswith("log")  # normalized, not raw LogError


def test_swallowed_alert_and_runbook_from_csharp(kb):
    docs, _ = kb
    alert = docs[("Alert", "orders-created-publish-failures")]
    assert alert["status"] == "needs-review"
    assert "orders.created" in alert["spec"]["expr"]["splunk"]
    assert ("Runbook", "orders-created-publish-failures") in docs


def test_dotnet_stack_and_resiliency(kb):
    docs, _ = kb
    assert any(f.get("name") == ".net" for f in docs[("TechStack", "orders-dotnet")]["spec"]["frameworks"])
    assert docs[("Deployment", "orders-dotnet")]["spec"]["hosting"] == "PCF"
    assert docs[("ResiliencyPattern", "inventory")]["spec"]["library"] == "polly"
