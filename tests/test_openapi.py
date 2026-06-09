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


# --- baseline diff (#7 versioning half) --------------------------------------------------------

def _changes():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-api")
    return [f for f in openapi.collect(ctx) if f.type == "api.contract.change"]


def test_baseline_spec_is_excluded_from_the_current_spec_ingest():
    # The `.sre/api-baseline/` spec must not double-count endpoints into the current-spec ingest.
    ctx = ScanContext(root=FIXTURE, repo="file://sample-api")
    eps = [f for f in openapi.collect(ctx) if f.type == "api.spec.endpoint"]
    assert all(not f.attrs["specPath"].startswith(openapi.BASELINE_DIR) for f in eps)
    assert {(f.attrs["method"], f.attrs["path"]) for f in eps} == {
        ("GET", "/api/v1/orders"), ("POST", "/api/v1/orders"), ("GET", "/api/v1/orders/{id}")}


def test_removed_operation_is_breaking_and_grounded_to_the_baseline():
    removed = next(c for c in _changes() if c.attrs["changeType"] == "operation-removed")
    assert removed.attrs["ref"] == "POST /api/v1/orders/{}/cancel"
    assert removed.attrs["breaking"] is True
    # An operation removal is provable only from the baseline, so it cites the baseline file.
    assert removed.evidence.path.startswith(openapi.BASELINE_DIR)


def test_added_operation_is_non_breaking_and_grounded_to_the_current_spec():
    added = next(c for c in _changes() if c.attrs["changeType"] == "operation-added")
    assert added.attrs["ref"] == "GET /api/v1/orders/{}"
    assert added.attrs["breaking"] is False
    assert added.evidence.path == "openapi.yaml"


def test_version_policy_flags_a_breaking_change_without_a_major_bump():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-api")
    vp = next(f for f in openapi.collect(ctx) if f.type == "api.contract.versionPolicy")
    assert vp.attrs["ok"] is False                # 1.1.0 -> 1.2.0 is not a major bump
    assert vp.attrs["breakingChanges"] == 1
    assert vp.attrs["majorBumped"] is False


def _diff(tmp_path, base: str, cur: str):
    (tmp_path / ".sre" / "api-baseline").mkdir(parents=True)
    (tmp_path / ".sre" / "api-baseline" / "openapi.yaml").write_text(base, encoding="utf-8")
    (tmp_path / "openapi.yaml").write_text(cur, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    facts = openapi.collect(ctx)
    return ([f for f in facts if f.type == "api.contract.change"],
            next(f for f in facts if f.type == "api.contract.versionPolicy"))


_OP = ('openapi: 3.0.3\ninfo: {{title: T, version: "{ver}"}}\npaths:\n'
       '  /things:\n    get:\n      responses: {{"200": {{description: ok}}}}\n{extra}')


def test_newly_required_parameter_is_a_breaking_change(tmp_path):
    base = _OP.format(ver="1.0.0", extra="")
    cur = ('openapi: 3.0.3\ninfo: {title: T, version: "1.0.1"}\npaths:\n'
           '  /things:\n    get:\n      parameters:\n'
           '        - {name: tenant, in: query, required: true}\n'
           '      responses: {"200": {description: ok}}\n')
    changes, vp = _diff(tmp_path, base, cur)
    req = next(c for c in changes if c.attrs["changeType"] == "required-parameter-added")
    assert req.attrs["breaking"] is True
    assert "query:tenant" in req.attrs["detail"]
    assert vp.attrs["ok"] is False                # breaking change, only a patch bump


def test_optional_parameter_added_is_not_a_change(tmp_path):
    base = _OP.format(ver="1.0.0", extra="")
    cur = ('openapi: 3.0.3\ninfo: {title: T, version: "1.0.1"}\npaths:\n'
           '  /things:\n    get:\n      parameters:\n'
           '        - {name: tenant, in: query, required: false}\n'
           '      responses: {"200": {description: ok}}\n')
    changes, vp = _diff(tmp_path, base, cur)
    assert not changes                            # an optional parameter is non-breaking and elided
    assert vp.attrs["ok"] is True


def test_major_bump_satisfies_the_version_policy(tmp_path):
    base = _OP.format(ver="1.4.0",
                      extra="  /old:\n    get:\n      responses: {\"200\": {description: ok}}\n")
    cur = _OP.format(ver="2.0.0", extra="")       # /old removed (breaking) but major bumped 1 -> 2
    changes, vp = _diff(tmp_path, base, cur)
    assert any(c.attrs["breaking"] for c in changes)
    assert vp.attrs["ok"] is True and vp.attrs["majorBumped"] is True


def test_no_baseline_means_no_diff_facts(tmp_path):
    (tmp_path / "openapi.yaml").write_text(_OP.format(ver="1.0.0", extra=""), encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    facts = openapi.collect(ctx)
    assert not [f for f in facts if f.type.startswith("api.contract")]
