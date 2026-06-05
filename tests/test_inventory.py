"""P2 inventory kinds: TechStack, Deployment, Dependency, Interface, DataStore,
ConfigManagement — deterministic roll-ups, all verified, on the fixture."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.pipeline import run as run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    work = tmp_path_factory.mktemp("work")
    r = run_pipeline(str(FIXTURE), work_root=str(work), run_id="inv", to_stage="validate")
    out = {}
    for p in (r.root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        out[(d["kind"], d["metadata"]["name"])] = d
    return out


def test_techstack(docs):
    ts = docs[("TechStack", "order-service")]
    assert ts["status"] == "verified"
    assert any(f.get("name") == "spring-boot" for f in ts["spec"]["frameworks"])


def test_deployment_is_pcf_with_capacity(docs):
    spec = docs[("Deployment", "order-service")]["spec"]
    assert spec["hosting"] == "PCF"
    assert spec["instances"] == 3
    assert "orders-postgres" in spec["services"]
    assert spec["healthCheck"]["type"] == "http"


def test_dependencies_classified(docs):
    assert docs[("Dependency", "orders-postgres")]["spec"]["type"] == "datastore"
    assert docs[("Dependency", "order-kafka")]["spec"]["type"] == "broker"
    http = docs[("Dependency", "inventory-http")]["spec"]
    assert http["type"] == "http"
    assert http["criticality"] == "contained"  # behind a circuit breaker


def test_datastore(docs):
    spec = docs[("DataStore", "orders-postgres")]["spec"]
    assert spec["engine"] == "postgres"
    assert "OrderRepository" in spec["accessedBy"]


def test_interface_unifies_rest_and_async(docs):
    spec = docs[("Interface", "order-service")]["spec"]
    assert spec["style"] == "rest+async"
    assert any(e["path"] == "/api/v1/orders" for e in spec["endpoints"])
    assert any(c["channel"] == "order.created" for c in spec["channels"])


def test_configmanagement(docs):
    spec = docs[("ConfigManagement", "order-service")]["spec"]
    assert "application.yml" in spec["sources"]
