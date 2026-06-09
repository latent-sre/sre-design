"""Estate analysis: across order-service + billing-service (which share orders-postgres),
build a cross-service Topology and a co-tenancy BlastRadius for the shared DB."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.estate import run_estate

FIX = Path(__file__).parent / "fixtures"
ORDER = FIX / "sample-spring-pcf"
BILLING = FIX / "sample-billing-pcf"


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    work = tmp_path_factory.mktemp("w")
    r = run_estate([str(ORDER), str(BILLING)], work_root=str(work), run_id="e")
    out = {}
    for p in (r.root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        out[(d["kind"], d["metadata"]["name"])] = d
    return out


def test_topology_has_both_services_and_shared_db(docs):
    topo = docs[("Topology", "estate")]
    assert topo["status"] == "verified"
    names = {n["name"] for n in topo["spec"]["nodes"]}
    assert {"order-service", "billing-service", "orders-postgres"} <= names
    binds = {(e["from"], e["to"]) for e in topo["spec"]["edges"] if e["to"] == "orders-postgres"}
    assert ("order-service", "orders-postgres") in binds
    assert ("billing-service", "orders-postgres") in binds


def test_cotenancy_blast_radius_for_shared_db(docs):
    co = docs[("BlastRadius", "orders-postgres-cotenancy")]
    assert co["status"] == "verified"  # provenance spans both repos and still verifies
    assert set(co["spec"]["impactedServices"]) == {"order-service", "billing-service"}
    assert co["spec"]["stateful"]["dataLossRisk"] is True
    assert co["spec"]["severityHint"] == "critical"


def test_unshared_resources_are_not_cotenancy(docs):
    assert ("BlastRadius", "order-kafka-cotenancy") not in docs
    assert ("BlastRadius", "billing-kafka-cotenancy") not in docs


def test_duplicate_target_basenames_are_rejected(tmp_path):
    """Evidence is keyed by `file://<basename>`: two targets named `api` would silently share one
    key and the first service's provenance would verify against the second service's files."""
    for team in ("team-a", "team-b"):
        (tmp_path / team / "api").mkdir(parents=True)
    with pytest.raises(ValueError, match="duplicate estate target basename"):
        run_estate([str(tmp_path / "team-a" / "api"), str(tmp_path / "team-b" / "api")],
                   work_root=str(tmp_path / "w"), run_id="dup")


def test_same_target_listed_twice_is_idempotent(tmp_path_factory):
    """Shell-glob overlap can list one path twice: it must scan once, not double-count the
    service in the topology and reports."""
    work = tmp_path_factory.mktemp("dup2")
    r = run_estate([str(ORDER), str(ORDER), str(BILLING)], work_root=str(work), run_id="idem")
    assert sorted(r.services) == ["billing-service", "order-service"]
