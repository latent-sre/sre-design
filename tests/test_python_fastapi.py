"""Python / FastAPI collector — breadth to a third stack (after Java/Spring + .NET/Steeltoe).

Proves the same engine extracts byte-grounded facts from FastAPI and the *unchanged* scaffolder
turns them into the same validated KB kinds (Interface, TechStack, Architecture, ...).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.parsing import parse
from sre_kb.pipeline import run as run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample-fastapi"


def _facts():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-fastapi", commit=LOCAL_COMMIT)
    return scan(ctx), ctx


# --------------------------------------------------------------- parser

def test_parser_reads_decorators_calls_and_spans():
    m = parse("python", '@app.get("/x")\nasync def h(i):\n    httpx.get(i)\n')
    [fn] = m.types[0].methods
    assert fn.name == "h"
    assert fn.annotations == {"app.get": {"": "/x"}}
    assert fn.start == 1 and fn.name_line == 2          # span starts at the decorator
    assert [(c.receiver, c.method) for c in fn.calls] == [("httpx", "get")]


# --------------------------------------------------------------- collector facts

def test_endpoints_and_egress_are_extracted_with_provenance():
    fs, ctx = _facts()
    eps = {(f.attrs["method"], f.attrs["path"]) for f in fs.of("rest.endpoint")}
    assert eps == {("GET", "/orders/{order_id}"), ("POST", "/orders"),
                   ("POST", "/sync"), ("GET", "/health")}
    # every endpoint cites real bytes
    for f in fs.of("rest.endpoint"):
        assert f.evidence.path.endswith("main.py") and f.evidence.source_tier == "ast"
    assert any(f.attrs.get("client") == "httpx" for f in fs.of("http.egress"))


def test_generic_receivers_do_not_over_match_as_http_egress(tmp_path):
    """Regression: a DB/ORM `session.get(...)` or cache `client.get(...)` must NOT become an
    http.egress fact — only real HTTP client modules (httpx/requests/aiohttp) count."""
    from sre_kb.collectors.python_fastapi import endpoints

    (tmp_path / "svc.py").write_text(
        "import httpx\n"
        "def handler(session, client):\n"
        "    session.get(123)\n"          # DB/ORM session — not HTTP
        "    client.send(123)\n"          # generic client — not HTTP
        "    httpx.get('http://x')\n",    # the only real egress
        encoding="utf-8",
    )
    ctx = ScanContext(root=tmp_path, repo="file://x", commit=LOCAL_COMMIT)
    egress = endpoints.collect(ctx)
    clients = {f.attrs["client"] for f in egress if f.type == "http.egress"}
    assert clients == {"httpx"}          # session/client did not over-match


def test_tech_stack_facts_are_python():
    fs, _ = _facts()
    fw = fs.first("tech.framework")
    rt = fs.first("tech.runtime")
    assert fw and fw.attrs["name"] == "fastapi"
    assert rt and rt.attrs["language"] == "python" and rt.attrs["buildTool"] == "pip"
    assert {"fastapi", "httpx"} <= {f.attrs["name"] for f in fs.of("tech.dependency")}


def test_self_gating_on_a_non_python_repo():
    spring = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
    ctx = ScanContext(root=spring, repo="file://spring", commit=LOCAL_COMMIT)
    from sre_kb.collectors.python_fastapi import endpoints
    assert endpoints.collect(ctx) == []  # no *.py -> nothing


# --------------------------------------------------------------- end-to-end KB

def test_fastapi_service_yields_a_validated_kb(tmp_path):
    r = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="fa", to_stage="validate")
    docs = {}
    for sub in ("kb/verified", "kb/needs-review"):
        for p in (r.root / sub).rglob("*.yaml"):
            d = yaml.safe_load(p.read_text())
            docs[(d["kind"], d["metadata"]["name"])] = d

    ts = docs[("TechStack", "orders-api")]
    assert ts["spec"]["languages"] == ["python"] and ts["spec"]["runtime"] == "cpython"
    assert ts["spec"]["buildTool"] == "pip"

    itf = docs[("Interface", "orders-api")]
    paths = {e["path"] for e in itf["spec"]["endpoints"]}
    assert {"/orders/{order_id}", "/orders", "/health"} <= paths

    from sre_kb.validation import validate_kb_tree
    bad = [x for x in validate_kb_tree(r.root / "kb") if not x.ok]
    assert not bad, [(x.path, x.errors) for x in bad]


def test_python_swallow_is_confirmed_by_the_gap_finder():
    # Python parity: the swallow detector now works on try/except, so the swallowed-failure
    # confirmation probe grounds a Python swallow and graduates it to Tier-A.
    from sre_kb.collectors.llm import gap_finder
    from sre_kb.collectors.llm.gap_finder import Proposal

    ctx = ScanContext(root=FIXTURE, repo="file://sample-fastapi", commit=LOCAL_COMMIT)
    res = gap_finder.collect_from_proposals(ctx, [
        Proposal("swallowed-failure", 'httpx.post(f"{INVENTORY}/sync", json=body)',
                 target="inventory", severity="high"),
    ])
    [out] = res.outcomes
    assert out.result == "confirmed"
    assert res.facts[0].evidence.source_tier == "ast"  # graduated, cross-stack
