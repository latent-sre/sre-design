"""cf-env snapshot (§4.3): credential-stripped `.sre/cf-env.json` -> typed service
instances + org/space, with credentials never reaching a fact in either accepted shape."""

from __future__ import annotations

import json

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common import cf_env
from sre_kb.synth.inventory import inventory_docs

_REDACTED = {
    "app": "order-service",
    "capturedAt": "2026-06-01T12:00:00Z",
    "organization": "acme-org",
    "space": "prod",
    "services": [
        {"name": "orders-postgres", "label": "postgres", "plan": "standard",
         "tags": ["relational"], "managed": True},
        {"name": "audit-cups", "label": "user-provided"},
    ],
}

_RAW = {
    "VCAP_APPLICATION": json.dumps({"organization_name": "acme-org", "space_name": "dev",
                                    "cf_api": "https://api.sys.acme"}),
    "VCAP_SERVICES": json.dumps({"postgres": [
        {"name": "orders-postgres", "label": "postgres", "plan": "standard",
         "tags": ["relational"],
         "credentials": {"uri": "postgres://user:hunter2@db/orders"}},  # pragma: allowlist secret
    ]}),
}


def _facts(tmp_path, doc):
    (tmp_path / ".sre").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".sre" / "cf-env.json").write_text(json.dumps(doc), encoding="utf-8")
    return cf_env.collect(ScanContext(root=tmp_path, repo="file://x"))


def test_redacted_shape_yields_space_and_typed_instances(tmp_path):
    facts = _facts(tmp_path, _REDACTED)
    space = next(f for f in facts if f.type == "pcf.space")
    assert space.attrs["organization"] == "acme-org" and space.attrs["space"] == "prod"
    assert space.attrs["capturedAt"] == "2026-06-01T12:00:00Z"
    by_name = {f.attrs["name"]: f.attrs for f in facts if f.type == "pcf.service-instance"}
    assert by_name["orders-postgres"]["plan"] == "standard"
    assert by_name["orders-postgres"]["managed"] is True
    assert by_name["audit-cups"]["managed"] is False  # user-provided label
    assert all(a["source"] == "cf-env-snapshot" for a in by_name.values())


def test_raw_vcap_shape_reads_only_the_allowlist_credentials_never_leak(tmp_path):
    facts = _facts(tmp_path, _RAW)
    space = next(f for f in facts if f.type == "pcf.space")
    assert space.attrs["space"] == "dev"
    inst = next(f for f in facts if f.type == "pcf.service-instance")
    assert inst.attrs["name"] == "orders-postgres" and inst.attrs["plan"] == "standard"
    blob = json.dumps({f.type: f.attrs for f in facts})
    assert "hunter2" not in blob and "credentials" not in blob and "cf_api" not in blob


def test_snapshot_outside_sre_dir_is_ignored(tmp_path):
    (tmp_path / "cf-env.json").write_text(json.dumps(_REDACTED), encoding="utf-8")
    assert cf_env.collect(ScanContext(root=tmp_path, repo="file://x")) == []


def test_garbage_snapshot_is_a_grounded_parse_error(tmp_path):
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "cf-env.json").write_text("not json", encoding="utf-8")
    facts = cf_env.collect(ScanContext(root=tmp_path, repo="file://x"))
    assert [f.type for f in facts] == ["collector.parse_error"]


def test_snapshot_upgrades_dependency_and_populates_pcf_spaces(tmp_path):
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: order-service\n  services:\n  - orders-postgres\n",
        encoding="utf-8")
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "cf-env.json").write_text(json.dumps(_REDACTED), encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    docs = inventory_docs(scan(ctx), ctx, "order-service")
    dep = next(d["spec"] for d in docs if d["kind"] == "Dependency"
               and d["spec"]["name"] == "orders-postgres")
    assert dep["type"] == "datastore" and dep["engine"] == "postgres"
    assert dep["plan"] == "standard" and dep["managed"] is True
    assert dep["snapshot"] == {"capturedAt": "2026-06-01T12:00:00Z"}
    topo = next(d["spec"] for d in docs if d["kind"] == "Topology")
    assert topo["pcfSpaces"] == [{"organization": "acme-org", "space": "prod",
                                  "services": ["order-service"]}]


def test_snapshot_label_classifies_what_the_name_cannot(tmp_path):
    """A binding named without an engine hint ('orders-data') types as datastore once the
    snapshot's broker label says postgres."""
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: svc\n  services:\n  - orders-data\n", encoding="utf-8")
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "cf-env.json").write_text(json.dumps({
        "organization": "acme-org", "space": "prod",
        "services": [{"name": "orders-data", "label": "postgres", "plan": "small"}],
    }), encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    docs = inventory_docs(scan(ctx), ctx, "svc")
    dep = next(d["spec"] for d in docs if d["kind"] == "Dependency")
    assert dep["type"] == "datastore" and dep["engine"] == "postgres"


def test_string_tags_value_is_dropped_not_exploded(tmp_path):
    """`"tags": "relational"` (string, not list) must not become per-character tags."""
    facts = _facts(tmp_path, {"organization": "o", "space": "s", "services": [
        {"name": "db", "label": "postgres", "tags": "relational"}]})
    inst = next(f for f in facts if f.type == "pcf.service-instance")
    assert inst.attrs["tags"] == []
