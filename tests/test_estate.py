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


def test_spa_connects_to_its_backend_with_zero_declaration(tmp_path):
    """§5.4: a React repo declaring its API via vite proxy resolves to a real
    frontend -> service edge through the same route<->baseUrl join, and the SPA's node
    renders as `frontend`."""
    spa = tmp_path / "shop-ui"
    spa.mkdir()
    (spa / "package.json").write_text(
        '{"name": "shop-ui", "dependencies": {"react": "^18.0.0"}}', encoding="utf-8")
    (spa / "vite.config.ts").write_text(
        "export default { server: { proxy: {"
        " '/api': { target: 'http://orders.apps.internal' } } } }\n",
        encoding="utf-8")
    api = tmp_path / "orders"
    api.mkdir()
    (api / "manifest.yml").write_text(
        "applications:\n- name: orders\n  routes:\n  - route: orders.apps.internal\n",
        encoding="utf-8")
    r = run_estate([str(spa), str(api)], work_root=str(tmp_path / "w"), run_id="spa")
    topo = next(yaml.safe_load(p.read_text()) for p in (r.root / "kb").rglob("estate.yaml"))
    nodes = {n["name"]: n["type"] for n in topo["spec"]["nodes"]}
    assert nodes["shop-ui"] == "frontend"
    assert {"from": "shop-ui", "to": "orders", "relation": "calls"} in topo["spec"]["edges"]


def test_breaking_contract_change_blasts_into_scanned_consumers(tmp_path):
    """§5.5: a provider with a spec gets contract-backed calls edges, and its breaking
    baseline-diff changes become an estate finding naming the impacted consumers."""
    provider = tmp_path / "orders"
    (provider / ".sre" / "api-baseline").mkdir(parents=True)
    (provider / "manifest.yml").write_text(
        "applications:\n- name: orders\n  routes:\n  - route: orders.apps.internal\n",
        encoding="utf-8")
    (provider / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo: {title: orders, version: 2.0.0}\npaths:\n"
        "  /orders:\n    get: {operationId: list}\n",
        encoding="utf-8")
    (provider / ".sre" / "api-baseline" / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo: {title: orders, version: 1.0.0}\npaths:\n"
        "  /orders:\n    get: {operationId: list}\n"
        "  /orders/{id}:\n    delete: {operationId: remove}\n",  # removed -> breaking
        encoding="utf-8")
    consumer = tmp_path / "shop"
    (consumer / "src/main/resources").mkdir(parents=True)
    (consumer / "manifest.yml").write_text(
        "applications:\n- name: shop\n", encoding="utf-8")
    (consumer / "src/main/resources/application.yml").write_text(
        "clients:\n  orders:\n    base-url: orders.apps.internal\n    timeout: 2s\n",
        encoding="utf-8")
    r = run_estate([str(provider), str(consumer)], work_root=str(tmp_path / "w"), run_id="api")
    topo = next(yaml.safe_load(p.read_text()) for p in (r.root / "kb").rglob("estate.yaml"))
    assert {"from": "shop", "to": "orders", "relation": "calls",
            "contract": "openapi"} in topo["spec"]["edges"]
    blast = [f for f in (r.findings or []) if f["type"] == "api-breaking-change-blast"]
    assert len(blast) == 1
    assert blast[0]["provider"] == "orders"
    assert blast[0]["impactedServices"] == ["shop"]
    assert blast[0]["changes"] == ["operation-removed DELETE /orders/{}"]  # normPath ref


def test_breaking_change_with_no_scanned_consumer_is_not_an_estate_finding(tmp_path):
    """No resolved consumer -> the breaking change stays the provider's single-repo concern
    (the Interface contract block), not estate noise."""
    provider = tmp_path / "orders"
    (provider / ".sre" / "api-baseline").mkdir(parents=True)
    (provider / "manifest.yml").write_text("applications:\n- name: orders\n", encoding="utf-8")
    (provider / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo: {title: o, version: 2.0.0}\npaths:\n  /a:\n    get: {}\n",
        encoding="utf-8")
    (provider / ".sre" / "api-baseline" / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo: {title: o, version: 1.0.0}\npaths:\n"
        "  /a:\n    get: {}\n  /b:\n    get: {}\n",
        encoding="utf-8")
    lone = tmp_path / "lone"
    lone.mkdir()
    (lone / "manifest.yml").write_text("applications:\n- name: lone\n", encoding="utf-8")
    r = run_estate([str(provider), str(lone)], work_root=str(tmp_path / "w"), run_id="noc")
    assert [f for f in (r.findings or []) if f["type"] == "api-breaking-change-blast"] == []


def test_cotenancy_impact_folds_transitive_callers(tmp_path):
    """§5.7: a gateway that calls order-service degrades when the shared postgres fails —
    impactedServices includes the A->B->C reach, with the indirect subset labeled."""
    gw = tmp_path / "gateway"
    (gw / "src/main/resources").mkdir(parents=True)
    (gw / "manifest.yml").write_text("applications:\n- name: gateway\n", encoding="utf-8")
    (gw / "src/main/resources/application.yml").write_text(
        "clients:\n  orders:\n    base-url: order-service.apps.internal\n    timeout: 2s\n",
        encoding="utf-8")
    r = run_estate([str(gw), str(ORDER), str(BILLING)],
                   work_root=str(tmp_path / "w"), run_id="trans")
    co = next(yaml.safe_load(p.read_text())
              for p in (r.root / "kb").rglob("orders-postgres-cotenancy.yaml"))
    assert set(co["spec"]["impactedServices"]) == {"order-service", "billing-service", "gateway"}
    assert co["spec"]["indirectServices"] == ["gateway"]
    assert set(co["spec"]["coTenancy"][0]["sharedBy"]) == {"order-service", "billing-service"}
