"""API-contract ingest + drift (#7): OpenAPI spec vs detected endpoints in the Interface kind."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common import openapi
from sre_kb.synth.scaffold import scaffold

FIXTURE = Path(__file__).parent / "fixtures" / "sample-api"


def test_normalize_path_is_template_insensitive():
    assert openapi.normalize_path("/orders/{id}") == openapi.normalize_path("/orders/{orderId}")
    assert openapi.normalize_path("/orders/{id}/") == "/orders/{}"
    assert openapi.normalize_path("/") == "/"


def test_spec_operations_ingested_and_byte_grounded():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-api")
    facts = [f for f in openapi.collect(ctx) if f.type == "api.spec.endpoint"]
    keys = {(f.attrs["method"], f.attrs["path"]) for f in facts}
    assert keys == {("GET", "/api/v1/orders"), ("POST", "/api/v1/orders"),
                    ("GET", "/api/v1/orders/{id}")}
    assert all(f.attrs["specVersion"] == "1.2.0" for f in facts)
    assert all(f.evidence.detector == "common.openapi" for f in facts)


def _interface():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-api")
    docs = scaffold(scan(ctx), ctx)
    return next(d for d in docs if d["kind"] == "Interface")["spec"]


def test_contract_drift_surfaced_in_interface():
    spec = _interface()
    contract = spec["contract"]
    assert contract["source"] == "openapi" and contract["version"] == "1.2.0"
    assert contract["documented"] == 2                                  # POST + GET/{id}
    assert contract["undocumented"] == ["DELETE /api/v1/orders/{}"]     # code exposes, spec omits
    assert contract["specOnly"] == ["GET /api/v1/orders"]              # spec documents, no handler


def test_endpoints_carry_documented_flag():
    spec = _interface()
    by = {(e["method"], e["path"]): e for e in spec["endpoints"]}
    assert by[("POST", "/api/v1/orders")]["documented"] is True
    assert by[("DELETE", "/api/v1/orders/{id}")]["documented"] is False


def test_no_spec_means_no_contract_block(tmp_path):
    # a repo with endpoints but no OpenAPI doc -> no `documented`/`contract` (nothing to compare to)
    src = ("package x;\nimport org.springframework.web.bind.annotation.*;\n"
           "@RestController @RequestMapping(\"/a\") class C { @GetMapping public String g(){return \"\";} }\n")
    (tmp_path / "C.java").write_text(src, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    iface = next(d for d in scaffold(scan(ctx), ctx) if d["kind"] == "Interface")["spec"]
    assert "contract" not in iface
    assert "documented" not in iface["endpoints"][0]
