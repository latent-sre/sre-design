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


# --- .NET parity residuals (NEXT-INCREMENTS §4.2/§5.3/§7 leftovers) -------------------------
def test_authorize_attribute_emits_authz_fact(tmp_path):
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.dotnet_steeltoe import annotations as dotnet_annotations

    (tmp_path / "C.cs").write_text(
        "namespace Acme.Orders {\n"
        "  [ApiController]\n  [Authorize]\n  public class OrdersController {\n"
        "    [HttpGet]\n    public string Get() { return \"ok\"; }\n  }\n}\n",
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    authz = [f for f in dotnet_annotations.collect(ctx) if f.type == "security.authz"]
    assert len(authz) == 1
    assert authz[0].attrs == {"annotation": "[Authorize]", "target": "Acme.Orders.OrdersController"}


def test_swallowed_savechanges_emits_db_failure_fact(tmp_path):
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.dotnet_steeltoe import annotations as dotnet_annotations

    (tmp_path / "S.cs").write_text(
        "namespace Acme.Orders {\n"
        "  public class OrderService {\n"
        "    private OrdersDbContext _db;\n"
        "    private ILogger _logger;\n"
        "    public void Save(Order o) {\n"
        "      try {\n        _db.SaveChangesAsync();\n      } catch (Exception ex) {\n"
        "        _logger.LogError(\"order save failed {Id}\", o.Id);\n      }\n    }\n  }\n}\n",
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    lost = [f for f in dotnet_annotations.collect(ctx) if f.type == "swallowed.db.failure"]
    assert len(lost) == 1
    assert lost[0].attrs["repository"] == "OrdersDbContext"
    assert lost[0].attrs["level"] == "error"
    assert "order save failed" in lost[0].attrs["message"]


def test_steeltoe_config_server_uri_emits_config_source(tmp_path):
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.dotnet_steeltoe import config as dotnet_config

    (tmp_path / "app.csproj").write_text("<Project></Project>", encoding="utf-8")
    (tmp_path / "appsettings.json").write_text(
        '{"Spring": {"Cloud": {"Config": {"Uri": "http://config.internal:8888"}}}}',
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    srcs = [f for f in dotnet_config.collect(ctx) if f.type == "config.source"]
    assert len(srcs) == 1
    assert srcs[0].attrs == {"kind": "configserver", "uri": "http://config.internal:8888",
                             "optional": False}


def test_csproj_dependency_version_captured(tmp_path):
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.dotnet_steeltoe import build as dotnet_build

    (tmp_path / "app.csproj").write_text(
        '<Project><ItemGroup>\n'
        '  <PackageReference Include="Acme.Models" Version="1.2.3" />\n'
        '  <PackageReference Include="NoVersion" />\n'
        '</ItemGroup></Project>\n',
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    deps = {f.attrs["name"]: f.attrs for f in dotnet_build.collect(ctx)
            if f.type == "tech.dependency"}
    assert deps["Acme.Models"] == {"name": "Acme.Models", "version": "1.2.3"}
    assert deps["NoVersion"] == {"name": "NoVersion"}


def test_httpclient_url_literal_captured(tmp_path):
    """A literal URL argument lands on the http.egress fact — the consumer-side anchor the
    OpenAPI estate join needs (§5.5 residual; same capture in the Java/Node/Go/Python collectors)."""
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.dotnet_steeltoe import annotations as dotnet_annotations

    (tmp_path / "H.cs").write_text(
        "namespace Acme {\n  public class InventoryClient {\n"
        "    private HttpClient _http;\n"
        "    public void Reserve() { _http.GetAsync(\"http://inventory.apps.internal/api/v1/reserve\"); }\n"
        "    public void Ping() { _http.GetAsync(name); }\n  }\n}\n",
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    egress = [f for f in dotnet_annotations.collect(ctx) if f.type == "http.egress"]
    urls = [f.attrs.get("url") for f in egress]
    assert "http://inventory.apps.internal/api/v1/reserve" in urls
    assert None in urls  # a non-literal argument stays uncaptured, never guessed
