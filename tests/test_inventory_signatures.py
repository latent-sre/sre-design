"""HYBRID-PLAN §9.7 N5 — declarative inventory signatures. The datastore/broker/stack catalogs are
data, not code: classification is a table lookup, and widening to Node/Go is a row, not a branch.
These tests pin the classifier and the manifest breadth path (a Go/Node repo with no collector still
rolls up a TechStack)."""

from __future__ import annotations

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.inventory_signatures import (
    all_manifests,
    broker_kind,
    datastore_engine,
    is_broker,
    is_datastore,
    stack_for_manifests,
)
from sre_kb.models.facts import FactSet
from sre_kb.synth.inventory import inventory_docs
from sre_kb.validation.structural import validate_doc


# --- datastore / broker classification ------------------------------------------------------------
def test_datastore_engine_maps_names_to_canonical_engines():
    assert datastore_engine("orders-postgres") == "postgres"
    assert datastore_engine("user-mongo") == "mongodb"  # alias folds to the canonical name
    assert datastore_engine("session-ioredis") == "redis"  # a Node client name
    assert datastore_engine("cache-go-redis") == "redis"  # a Go client name
    assert datastore_engine("reporting-mariadb") == "mysql"
    assert datastore_engine("legacy-sqlserver") == "mssql"
    assert datastore_engine("payments-api") is None  # an HTTP service is not a datastore


def test_specific_engines_win_over_the_generic_fallback():
    # `mysql`/`mongodb` both contain a generic hint ("sql"/"db") but must resolve to the specific
    # engine — ordering (specific before generic) is the contract.
    assert datastore_engine("mysql") == "mysql"
    assert datastore_engine("mongodb") == "mongodb"
    assert datastore_engine("orders-db") == "database"  # only the generic fallback claims it
    assert datastore_engine("legacy-jdbc") == "sql"


def test_broker_kind_maps_names_across_ecosystems():
    assert broker_kind("order-kafka") == "kafka"
    assert broker_kind("events-kafkajs") == "kafka"  # Node
    assert broker_kind("events-sarama") == "kafka"   # Go
    assert broker_kind("billing-rabbitmq") == "rabbitmq"
    assert broker_kind("notify-amqp") == "rabbitmq"
    assert broker_kind("queue-sqs") == "sqs"
    assert broker_kind("orders-postgres") is None


def test_is_helpers_agree_with_the_classifiers():
    assert is_datastore("orders-postgres") and not is_datastore("order-kafka")
    assert is_broker("order-kafka") and not is_broker("orders-postgres")


# --- manifest -> stack ----------------------------------------------------------------------------
def test_stack_for_manifests_covers_node_and_go():
    go = stack_for_manifests(["go.mod"])
    assert (go.language, go.runtime, go.build_tool) == ("go", "go", "gomod")
    js = stack_for_manifests(["package.json"])
    assert (js.language, js.runtime, js.build_tool) == ("javascript", "node", "npm")
    ts = stack_for_manifests(["tsconfig.json", "package.json"])
    assert ts.language == "typescript"  # tsconfig wins over a bare package.json
    assert stack_for_manifests(["pom.xml"]).build_tool == "maven"
    assert stack_for_manifests(["build.gradle"]).build_tool == "gradle"
    assert stack_for_manifests(["Service.csproj"]).language == "csharp"  # glob match, case-insensitive
    assert stack_for_manifests(["README.md"]) is None


def test_go_wins_over_an_incidental_package_json():
    # A Go service whose tooling drags in a package.json must still resolve to Go (polyglot tie-break).
    assert stack_for_manifests(["package.json", "go.mod"]).language == "go"


def test_all_manifests_lists_the_scan_set():
    manifests = all_manifests()
    assert {"pom.xml", "go.mod", "package.json", "*.csproj"} <= set(manifests)
    assert len(manifests) == len(set(manifests))  # de-duplicated


# --- breadth path: a manifest-only repo still rolls up a TechStack --------------------------------
def _techstack(tmp_path, *manifests: tuple[str, str]):
    for name, body in manifests:
        (tmp_path / name).write_text(body, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://breadth", commit=LOCAL_COMMIT)
    docs = inventory_docs(FactSet(), ctx, "svc")
    return next((d for d in docs if d["kind"] == "TechStack"), None)


def test_go_repo_with_no_collector_still_gets_a_techstack(tmp_path):
    ts = _techstack(tmp_path, ("go.mod", "module github.com/acme/orders\n\ngo 1.22\n"))
    assert ts is not None
    assert ts["spec"]["languages"] == ["go"]
    assert ts["spec"]["runtime"] == "go" and ts["spec"]["buildTool"] == "gomod"
    assert ts["spec"]["frameworks"] == []  # presence-based: runtime known, framework not parsed
    assert ts["evidence"][0]["path"] == "go.mod"
    assert ts["status"] == "verified"
    assert validate_doc(ts) == []  # a real, schema-valid artifact


def test_node_repo_with_no_collector_still_gets_a_techstack(tmp_path):
    ts = _techstack(tmp_path, ("package.json", '{"name": "orders", "version": "1.0.0"}\n'))
    assert ts["spec"]["languages"] == ["javascript"]
    assert ts["spec"]["runtime"] == "node" and ts["spec"]["buildTool"] == "npm"
    assert validate_doc(ts) == []


def test_empty_repo_fabricates_no_techstack(tmp_path):
    # No manifest, no facts -> no TechStack (we never invent a default java stack from nothing).
    assert _techstack(tmp_path) is None
