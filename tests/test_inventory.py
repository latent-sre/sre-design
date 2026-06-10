"""P2 inventory kinds: TechStack, Deployment, Dependency, Interface,
ConfigManagement — deterministic roll-ups, all verified, on the fixture.
(DataStore folded into Dependency in S1 — see test_datastore_engine_folded_into_dependency.)"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.render.copilot import reliability_guardrails

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


def test_datastore_engine_folded_into_dependency(docs):
    # S1: the former DataStore kind is gone; a datastore/broker binding carries its engine here
    assert docs[("Dependency", "orders-postgres")]["spec"]["engine"] == "postgres"
    assert docs[("Dependency", "order-kafka")]["spec"]["engine"] == "kafka"
    assert ("DataStore", "orders-postgres") not in docs  # kind pruned


def test_interface_unifies_rest_and_async(docs):
    spec = docs[("Interface", "order-service")]["spec"]
    assert spec["style"] == "rest+async"
    assert any(e["path"] == "/api/v1/orders" for e in spec["endpoints"])
    assert any(c["channel"] == "order.created" for c in spec["channels"])


def test_configmanagement(docs):
    spec = docs[("ConfigManagement", "order-service")]["spec"]
    # Sources are the files the config facts cite (plus the manifest env block), not a constant.
    assert spec["sources"] == ["src/main/resources/application.yml", "pcf-manifest-env"]
    assert spec["refreshScope"] is False  # no @RefreshScope anywhere in the fixture


def test_single_service_topology(docs):
    # The app-centric graph the estate run merges, now emitted per run: the service, its
    # bound resources, and config-declared downstreams.
    spec = docs[("Topology", "order-service")]["spec"]
    nodes = {n["name"]: n["type"] for n in spec["nodes"]}
    assert nodes["order-service"] == "service"
    assert nodes["orders-postgres"] == "datastore"
    assert nodes["order-kafka"] == "broker"
    assert nodes["inventory"] == "external"
    assert {"from": "order-service", "to": "orders-postgres", "relation": "binds"} in spec["edges"]
    assert {"from": "order-service", "to": "inventory", "relation": "calls"} in spec["edges"]
    assert nodes["order.created"] == "topic"  # published channels are graph nodes too
    assert {"from": "order-service", "to": "order.created", "relation": "publishes"} in spec["edges"]


def test_interface_idempotency_matches_the_gap_signature(docs):
    # POST /api/v1/orders has no idempotency guard in scope — the same Tier-A signature that
    # emits the missing-idempotency gap drives the Interface fields, so they cannot disagree.
    post = next(e for e in docs[("Interface", "order-service")]["spec"]["endpoints"]
                if e["method"] == "POST")
    assert post["idempotent"] is False
    assert post["retrySafe"] is False


def test_security_posture_rolls_up_actuator_exposure(docs):
    # The fixture limits actuator exposure (health,info,prometheus) — a control, not a risk.
    spec = docs[("SecurityPosture", "order-service-security")]["spec"]
    assert "actuator-exposure-limited" in spec["controls"]
    assert "openRisks" not in spec


def test_security_posture_and_delivery_pipeline_from_a_secured_repo(tmp_path):
    """A secured service with a CI workflow fills the two formerly never-emitted kinds:
    SecurityPosture from security deps + authz annotations + broad actuator exposure, and
    DeliveryPipeline from the checked-in GitHub Actions workflow."""
    repo = tmp_path / "svc"
    (repo / "src/main/java/com/acme/vault").mkdir(parents=True)
    (repo / "src/main/resources").mkdir(parents=True)
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / "manifest.yml").write_text(
        "applications:\n- name: vault-service\n", encoding="utf-8")
    (repo / "pom.xml").write_text(
        "<project>\n  <dependencies>\n    <dependency>\n"
        "      <groupId>org.springframework.boot</groupId>\n"
        "      <artifactId>spring-boot-starter-oauth2-resource-server</artifactId>\n"
        "    </dependency>\n  </dependencies>\n</project>\n", encoding="utf-8")
    (repo / "src/main/resources/application.yml").write_text(
        "management:\n  endpoints:\n    web:\n      exposure:\n        include: '*'\n",
        encoding="utf-8")
    (repo / "src/main/java/com/acme/vault/VaultController.java").write_text(
        "package com.acme.vault;\n"
        "@RestController\n@RequestMapping(\"/api/v1/vault\")\n"
        "public class VaultController {\n"
        "    @PreAuthorize(\"hasRole('ADMIN')\")\n"
        "    @GetMapping(\"/{id}\")\n"
        "    public Secret get(@PathVariable String id) { return null; }\n"
        "}\n", encoding="utf-8")
    (repo / ".github/workflows/deploy.yml").write_text(
        "name: deploy\n"
        "on:\n  push:\n    branches: [main]\n"
        "jobs:\n"
        "  build:\n    steps:\n    - run: mvn -B package\n"
        "  deploy:\n    steps:\n    - run: cf push vault-service\n", encoding="utf-8")
    r = run_pipeline(str(repo), work_root=str(tmp_path / "w"), run_id="sec", to_stage="validate")
    out = {}
    for p in (r.root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        out[(d["kind"], d["metadata"]["name"])] = d

    sec = out[("SecurityPosture", "vault-service-security")]["spec"]
    assert sec["authn"] == "oauth2"
    assert sec["authz"] == "role-based"
    assert {"spring-security", "authz-annotations"} <= set(sec["controls"])
    assert any("broadly exposed" in r for r in sec["openRisks"])  # exposure '*' is a risk

    dp = out[("DeliveryPipeline", "deploy")]["spec"]
    assert dp["system"] == "github-actions"
    assert dp["stages"] == ["build", "deploy"]
    assert dp["branch"] == "main"


def test_derived_fields_from_a_guarded_refreshable_service(tmp_path):
    """One mini service exercises the other side of each derivation: a safe GET is idempotent,
    @RefreshScope flips ConfigManagement.refreshScope, and a save() in a logged-and-swallowed
    catch marks the datastore BlastRadius lossy."""
    repo = tmp_path / "svc"
    (repo / "src/main/java/com/acme/pay").mkdir(parents=True)
    (repo / "src/main/resources").mkdir(parents=True)
    (repo / "manifest.yml").write_text(
        "applications:\n- name: pay-service\n  services:\n  - pay-postgres\n",
        encoding="utf-8")
    (repo / "src/main/resources/application.yml").write_text(
        "clients:\n  billing:\n    base-url: http://billing.apps.internal\n    timeout: 2s\n",
        encoding="utf-8")
    (repo / "src/main/java/com/acme/pay/PayRepository.java").write_text(
        "package com.acme.pay;\n"
        "public interface PayRepository extends JpaRepository<Payment, String> {}\n",
        encoding="utf-8")
    (repo / "src/main/java/com/acme/pay/RefreshableClients.java").write_text(
        "package com.acme.pay;\n"
        "@RefreshScope\n@Component\npublic class RefreshableClients {}\n",
        encoding="utf-8")
    (repo / "src/main/java/com/acme/pay/PayController.java").write_text(
        "package com.acme.pay;\n"
        "@RestController\n@RequestMapping(\"/api/v1/payments\")\n"
        "public class PayController {\n"
        "    private static final Logger log = LoggerFactory.getLogger(PayController.class);\n"
        "    private final PayRepository payRepository;\n"
        "    public PayController(PayRepository payRepository) {\n"
        "        this.payRepository = payRepository;\n"
        "    }\n"
        "    @GetMapping(\"/{id}\")\n"
        "    public Payment get(@PathVariable String id) { return null; }\n"
        "    @PostMapping\n"
        "    public void create(@RequestBody Payment p) {\n"
        "        try {\n"
        "            payRepository.save(p);\n"
        "        } catch (Exception e) {\n"
        "            log.error(\"failed to persist payment {}\", p, e);\n"
        "        }\n"
        "    }\n"
        "}\n",
        encoding="utf-8")
    r = run_pipeline(str(repo), work_root=str(tmp_path / "w"), run_id="der", to_stage="validate")
    out = {}
    for p in (r.root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        out[(d["kind"], d["metadata"]["name"])] = d

    eps = {e["method"]: e for e in out[("Interface", "pay-service")]["spec"]["endpoints"]}
    assert eps["GET"]["idempotent"] is True and eps["GET"]["retrySafe"] is True
    assert eps["POST"]["idempotent"] is False  # save in scope has no idempotency guard

    assert out[("ConfigManagement", "pay-service")]["spec"]["refreshScope"] is True

    br = out[("BlastRadius", "pay-repository")]["spec"]
    assert br["stateful"]["dataLossRisk"] is True  # swallowed save = silent write loss

    # The lossy write gets the same Flow->Alert->Runbook chain a swallowed publish gets.
    alert = out[("Alert", "pay-repository-write-failures")]
    assert alert["status"] == "needs-review"
    assert alert["spec"]["signalSource"] == "log-pattern"
    rb = out[("Runbook", "pay-repository-write-failures")]
    assert rb["spec"]["trigger"]["alertRef"] == "pay-repository-write-failures"

    # The hard guardrail names the actual lossy mechanism — a DB write, not a publish.
    rules = reliability_guardrails(list(out.values()))
    db_rules = [r for r in rules if "persist" in r]
    assert db_rules and all("DB write" in r and "publish" not in r for r in db_rules)


def test_deployment_env_variant_gets_its_own_artifact(tmp_path):
    """A manifest-<env>.yml variant emits its own Deployment (<service>-<env>) instead of being
    dropped or overwriting the base manifest's contract."""
    from sre_kb.collectors import scan
    from sre_kb.collectors.base import ScanContext
    from sre_kb.synth.inventory import inventory_docs

    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: orders\n  instances: 1\n", encoding="utf-8")
    (tmp_path / "manifest-prod.yml").write_text(
        "applications:\n- name: orders\n  instances: 6\n", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    docs_ = inventory_docs(scan(ctx), ctx, "orders")
    deps = {d["metadata"]["name"]: d["spec"] for d in docs_ if d["kind"] == "Deployment"}
    assert deps["orders"]["instances"] == 1 and "environment" not in deps["orders"]
    assert deps["orders-prod"]["instances"] == 6 and deps["orders-prod"]["environment"] == "prod"


def test_configmanagement_includes_declared_external_sources(tmp_path):
    """A config-server import lands in ConfigManagement.sources alongside the citing file."""
    from sre_kb.collectors import scan
    from sre_kb.collectors.base import ScanContext
    from sre_kb.synth.inventory import inventory_docs

    res = tmp_path / "src" / "main" / "resources"
    res.mkdir(parents=True)
    (res / "application.yml").write_text(
        "spring:\n  config:\n    import: configserver:http://config.internal:8888\n",
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    docs_ = inventory_docs(scan(ctx), ctx, "orders")
    cm = next(d["spec"] for d in docs_ if d["kind"] == "ConfigManagement")
    assert "configserver:http://config.internal:8888" in cm["sources"]
    assert "src/main/resources/application.yml" in cm["sources"]


def test_multi_app_manifest_emits_one_deployment_per_app(tmp_path):
    """Two applications in one manifest must yield two Deployment docs — the old
    service-keyed naming silently overwrote the first with the second."""
    from sre_kb.collectors import scan
    from sre_kb.collectors.base import ScanContext
    from sre_kb.synth.inventory import inventory_docs

    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: api\n  instances: 2\n- name: worker\n  instances: 4\n",
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    docs_ = inventory_docs(scan(ctx), ctx, "api")
    deps = {d["metadata"]["name"]: d["spec"] for d in docs_ if d["kind"] == "Deployment"}
    assert deps["api"]["instances"] == 2
    assert deps["worker"]["instances"] == 4
