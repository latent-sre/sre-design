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
