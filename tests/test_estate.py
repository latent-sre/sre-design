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


def test_cotenancy_impacted_flows_join_each_tenants_flows(docs):
    # order-service binds one datastore, so its db-sink flow attributes to the shared postgres;
    # billing-service is read-only (no flow steps), so it contributes services but no flows.
    co = docs[("BlastRadius", "orders-postgres-cotenancy")]
    assert co["spec"]["impactedFlows"] == ["order-service/create-order"]


def test_unresolved_client_stays_an_external_node(docs):
    # inventory-service.apps.internal matches no scanned service's route -> external, as before
    topo = docs[("Topology", "estate")]
    nodes = {n["name"]: n["type"] for n in topo["spec"]["nodes"]}
    assert nodes["inventory"] == "external"


def test_client_base_url_resolves_to_a_scanned_services_route(tmp_path):
    """A config-declared baseUrl whose hostname matches another scanned service's PCF route
    becomes a real service->service edge, not a synthetic external node."""
    caller = tmp_path / "caller"
    (caller / "src/main/resources").mkdir(parents=True)
    (caller / "manifest.yml").write_text(
        "applications:\n- name: caller\n  routes:\n  - route: caller.apps.internal\n",
        encoding="utf-8")
    (caller / "src/main/resources/application.yml").write_text(
        # one scheme-less baseUrl (the common Spring style) and one with scheme+port+path:
        # both must normalize to the same host and resolve to the callee service
        "clients:\n"
        "  callee:\n    base-url: callee.apps.internal\n    timeout: 2s\n"
        "  callee-api:\n    base-url: http://callee.apps.internal:8080/api\n    timeout: 2s\n",
        encoding="utf-8")
    callee = tmp_path / "callee"
    callee.mkdir()
    (callee / "manifest.yml").write_text(
        "applications:\n- name: callee\n  routes:\n  - route: callee.apps.internal\n",
        encoding="utf-8")
    r = run_estate([str(caller), str(callee)], work_root=str(tmp_path / "w"), run_id="resolve")
    topo = next(yaml.safe_load(p.read_text()) for p in (r.root / "kb").rglob("estate.yaml"))
    assert {"from": "caller", "to": "callee", "relation": "calls"} in topo["spec"]["edges"]
    assert all(n["name"] != "callee" or n["type"] == "service" for n in topo["spec"]["nodes"])
    topo_md = (r.root / "projections" / "diagrams" / "topology.md").read_text()
    assert "```mermaid" in topo_md and "Legend:" in topo_md  # GitHub-renderable wrapper


def test_messaging_topic_joins_producer_and_consumer_repos(tmp_path):
    """order-service publishes order.created; the messaging fixture consumes it from another
    repo — the topic becomes a shared node with both edges, answering 'who consumes this?'."""
    r = run_estate([str(ORDER), str(FIX / "sample-messaging")],
                   work_root=str(tmp_path / "w"), run_id="topics")
    topo = next(yaml.safe_load(p.read_text()) for p in (r.root / "kb").rglob("estate.yaml"))
    nodes = {n["name"]: n["type"] for n in topo["spec"]["nodes"]}
    assert nodes["order.created"] == "topic"
    edges = topo["spec"]["edges"]
    assert {"from": "order-service", "to": "order.created", "relation": "publishes"} in edges
    assert {"from": "order.created", "to": "sample-messaging", "relation": "consumes"} in edges


def test_unshared_resources_are_not_cotenancy(docs):
    assert ("BlastRadius", "order-kafka-cotenancy") not in docs
    assert ("BlastRadius", "billing-kafka-cotenancy") not in docs


def test_duplicate_target_basenames_scan_with_distinct_identities(tmp_path):
    """Repo identity is the full file URI, so two targets both named `api` no longer collide:
    each service's provenance verifies against its own root, and the same-named services stay
    distinct nodes in the estate (the second disambiguated by its parent dir)."""
    for team in ("team-a", "team-b"):
        d = tmp_path / team / "api"
        d.mkdir(parents=True)
        (d / "manifest.yml").write_text("applications:\n- name: api\n", encoding="utf-8")
    r = run_estate([str(tmp_path / "team-a" / "api"), str(tmp_path / "team-b" / "api")],
                   work_root=str(tmp_path / "w"), run_id="dup")
    assert sorted(r.services) == ["api", "team-b-api"]
    assert r.by_status.get("verified", 0) >= 1  # cross-repo provenance verifies, not downgraded


def test_same_target_listed_twice_is_idempotent(tmp_path_factory):
    """Shell-glob overlap can list one path twice: it must scan once, not double-count the
    service in the topology and reports."""
    work = tmp_path_factory.mktemp("dup2")
    r = run_estate([str(ORDER), str(ORDER), str(BILLING)], work_root=str(work), run_id="idem")
    assert sorted(r.services) == ["billing-service", "order-service"]


def _lib_repo(root: Path, name: str, version: str) -> None:
    root.mkdir(parents=True)
    (root / "manifest.yml").write_text(
        f"applications:\n- name: {name}\n", encoding="utf-8")
    (root / "pom.xml").write_text(
        "<project>\n<dependencies>\n<dependency>\n"
        "<groupId>com.acme</groupId>\n<artifactId>acme-models</artifactId>\n"
        f"<version>{version}</version>\n</dependency>\n</dependencies>\n</project>\n",
        encoding="utf-8")


def test_internal_library_joins_services_and_flags_version_skew(tmp_path):
    """Allowlisted internal dependencies become library nodes with uses-library edges; two
    services pinning different versions of the same library raise a version-skew finding."""
    _lib_repo(tmp_path / "a", "svc-a", "1.0.0")
    _lib_repo(tmp_path / "b", "svc-b", "2.0.0")
    r = run_estate([str(tmp_path / "a"), str(tmp_path / "b")],
                   work_root=str(tmp_path / "w"), run_id="libs",
                   internal_namespaces=["com.acme*"])
    topo = next(yaml.safe_load(p.read_text()) for p in (r.root / "kb").rglob("estate.yaml"))
    nodes = {n["name"]: n["type"] for n in topo["spec"]["nodes"]}
    assert nodes["acme-models"] == "library"
    edges = topo["spec"]["edges"]
    assert {"from": "svc-a", "to": "acme-models", "relation": "uses-library"} in edges
    assert {"from": "svc-b", "to": "acme-models", "relation": "uses-library"} in edges
    skew = [f for f in (r.findings or []) if f["type"] == "library-version-skew"]
    assert len(skew) == 1
    assert skew[0]["versions"] == {"svc-a": "1.0.0", "svc-b": "2.0.0"}
    # The finding also lands in the written estate report (the reviewer-facing record).
    import json
    report = json.loads(r.report_path.read_text())
    assert report["findings"] == skew


def test_no_allowlist_means_no_library_lineage(tmp_path):
    """Default (empty allowlist): dependency facts never become graph nodes — third-party
    libraries would drown the topology."""
    _lib_repo(tmp_path / "a", "svc-a", "1.0.0")
    _lib_repo(tmp_path / "b", "svc-b", "2.0.0")
    r = run_estate([str(tmp_path / "a"), str(tmp_path / "b")],
                   work_root=str(tmp_path / "w"), run_id="nolibs")
    topo = next(yaml.safe_load(p.read_text()) for p in (r.root / "kb").rglob("estate.yaml"))
    assert all(n["type"] != "library" for n in topo["spec"]["nodes"])
    assert not r.findings


def test_same_version_everywhere_is_lineage_without_skew(tmp_path):
    _lib_repo(tmp_path / "a", "svc-a", "1.0.0")
    _lib_repo(tmp_path / "b", "svc-b", "1.0.0")
    r = run_estate([str(tmp_path / "a"), str(tmp_path / "b")],
                   work_root=str(tmp_path / "w"), run_id="same",
                   internal_namespaces=["com.acme*"])
    topo = next(yaml.safe_load(p.read_text()) for p in (r.root / "kb").rglob("estate.yaml"))
    assert any(n["type"] == "library" for n in topo["spec"]["nodes"])
    assert not r.findings
