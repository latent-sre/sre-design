"""Cross-file call and operational-evidence atlas acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from sre_kb.atlas import build_atlas, write_atlas


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(root: Path, projects: list[dict]) -> None:
    data = {
        "apiVersion": "sre.kb/atlas-config/v1alpha1",
        "projects": projects,
        "exclude": [".work/**", "docs/codebase-atlas/generated/**"],
        "output": {
            "path": "docs/codebase-atlas/generated",
            "maxDiagramNodes": 80,
            "html": False,
        },
    }
    _write(root / ".sre" / "atlas.yaml", yaml.safe_dump(data, sort_keys=False))


def test_python_and_java_calls_resolve_only_to_repo_definitions(tmp_path: Path):
    _write(tmp_path / "py" / "client.py", "def fetch():\n    return 1\n")
    _write(
        tmp_path / "py" / "service.py",
        "import client\n\ndef run():\n    return client.fetch()\n",
    )
    _write(
        tmp_path / "java" / "InventoryClient.java",
        "package demo; class InventoryClient { void fetch() {} }\n",
    )
    _write(
        tmp_path / "java" / "OrderService.java",
        """\
package demo;
class OrderService {
  private final InventoryClient inventoryClient;
  void run() { inventoryClient.fetch(); }
}
""",
    )
    _config(
        tmp_path,
        [
            {"name": "python", "roots": ["py"]},
            {"name": "java", "roots": ["java"]},
        ],
    )

    snapshot, _ = build_atlas(tmp_path)
    nodes = {node.path: node.id for node in snapshot.nodes if node.path}
    calls = {
        (edge.source, edge.target, edge.resolver)
        for edge in snapshot.edges
        if edge.kind == "calls" and not edge.unresolved
    }

    assert (
        nodes["py/service.py"],
        nodes["py/client.py"],
        "python:ast-call",
    ) in calls
    assert (
        nodes["java/OrderService.java"],
        nodes["java/InventoryClient.java"],
        "java:tree-sitter-call",
    ) in calls
    assert all(edge.scope == "source" for edge in snapshot.edges if edge.kind == "calls")
    assert all(
        evidence.evidenceClass == "STATIC_RESOLVED"
        for edge in snapshot.edges
        if edge.kind == "calls"
        for evidence in edge.evidence
    )


def test_ambiguous_type_call_remains_an_explicit_unknown(tmp_path: Path):
    _write(tmp_path / "one" / "Client.java", "package one; class Client { void fetch() {} }\n")
    _write(tmp_path / "two" / "Client.java", "package two; class Client { void fetch() {} }\n")
    _write(
        tmp_path / "app" / "Use.java",
        "package app; class Use { Client client; void run() { client.fetch(); } }\n",
    )
    _config(
        tmp_path,
        [{"name": "fixture", "roots": ["one", "two", "app"]}],
    )

    snapshot, _ = build_atlas(tmp_path)

    assert not [edge for edge in snapshot.edges if edge.kind == "calls"]
    assert any(
        unknown.code == "resolver.java-ambiguous-call-target" and unknown.path == "app/Use.java"
        for unknown in snapshot.unknowns
    )


def test_csharp_javascript_typescript_and_go_import_calls_resolve(tmp_path: Path):
    _write(
        tmp_path / "dotnet" / "Client.cs",
        "namespace Demo.Client; class InventoryClient { void Fetch() {} }\n",
    )
    _write(
        tmp_path / "dotnet" / "Service.cs",
        """\
using Demo.Client;
namespace Demo.App;
class Service {
  InventoryClient client;
  void Run() { client.Fetch(); }
}
""",
    )
    _write(
        tmp_path / "web" / "client.js",
        "export function fetchInventory() { return 1; }\n",
    )
    _write(
        tmp_path / "web" / "service.js",
        "import * as client from './client.js';\nclient.fetchInventory();\n",
    )
    _write(
        tmp_path / "ts" / "client.ts",
        "export function fetchInventory(): number { return 1; }\n",
    )
    _write(
        tmp_path / "ts" / "service.ts",
        "import { fetchInventory as fetchIt } from './client';\nfetchIt();\n",
    )
    _write(tmp_path / "go" / "go.mod", "module example.com/app\n")
    _write(
        tmp_path / "go" / "client" / "client.go",
        "package client\nfunc Fetch() int { return 1 }\n",
    )
    _write(
        tmp_path / "go" / "service" / "main.go",
        """\
package service
import "example.com/app/client"
func Run() { client.Fetch() }
""",
    )
    _config(
        tmp_path,
        [
            {"name": "dotnet", "roots": ["dotnet"]},
            {"name": "web", "roots": ["web"]},
            {"name": "typescript", "roots": ["ts"]},
            {
                "name": "go",
                "roots": ["go"],
                "manifests": ["go/go.mod"],
            },
        ],
    )

    snapshot, _ = build_atlas(tmp_path)
    nodes = {node.path: node.id for node in snapshot.nodes if node.path}
    calls = {
        (edge.source, edge.target, edge.resolver)
        for edge in snapshot.edges
        if edge.kind == "calls"
    }

    assert (
        nodes["dotnet/Service.cs"],
        nodes["dotnet/Client.cs"],
        "csharp:tree-sitter-call",
    ) in calls
    assert (
        nodes["web/service.js"],
        nodes["web/client.js"],
        "javascript:tree-sitter-call",
    ) in calls
    assert (
        nodes["ts/service.ts"],
        nodes["ts/client.ts"],
        "typescript:tree-sitter-call",
    ) in calls
    go_edge = next(
        edge
        for edge in snapshot.edges
        if edge.source == nodes["go/service/main.go"]
        and edge.kind == "calls"
        and edge.resolver == "go:tree-sitter-call"
    )
    node_by_id = {node.id: node for node in snapshot.nodes}
    assert node_by_id[go_edge.target].name == "example.com/app/client"


def test_operational_roots_emit_static_signals_and_a_runbook_input_report(tmp_path: Path):
    _write(tmp_path / "src" / "app.py", "def app():\n    return 1\n")
    _write(
        tmp_path / "ops" / "Dockerfile",
        "FROM python:3.13-slim\nHEALTHCHECK CMD curl --fail http://localhost/health\nUSER 10001\n",
    )
    _write(tmp_path / "ops" / "restart.sh", "systemctl restart example-api\n")
    _write(tmp_path / "ops" / "migration.sql", "ALTER TABLE jobs ADD COLUMN state TEXT;\n")
    _write(
        tmp_path / "ops" / "compose.yaml",
        "services:\n  api:\n    image: example/api\n    healthcheck:\n      test: curl /health\n",
    )
    _config(
        tmp_path,
        [
            {
                "name": "fixture",
                "roots": ["src"],
                "operationalRoots": ["ops"],
            }
        ],
    )

    snapshot, output = write_atlas(tmp_path)

    assert {node.language for node in snapshot.nodes if node.type == "operational-file"} == {
        "bash",
        "dockerfile",
        "sql",
        "yaml",
    }
    categories = {signal.category for signal in snapshot.signals}
    assert {
        "database.schema-change",
        "deployment.base-image",
        "deployment.healthcheck",
        "deployment.image",
        "deployment.user",
        "service.control",
    } <= categories
    assert all(signal.evidence.evidenceClass == "STATIC_EXTRACTED" for signal in snapshot.signals)
    report = (output / "OPERATIONAL-SIGNALS.md").read_text(encoding="utf-8")
    assert "STATIC_EXTRACTED" in report
    assert "runtime evidence" in report.lower()
    assert "ops/restart.sh:1" in report
    assert (output / "call-graph.md").is_file()
    data = json.loads((output / "atlas.json").read_text(encoding="utf-8"))
    assert len(data["signals"]) == len(snapshot.signals)


def test_test_roots_do_not_emit_operational_signals(tmp_path: Path):
    _write(tmp_path / "src" / "app.py", "def app():\n    return 1\n")
    _write(
        tmp_path / "tests" / "test_app.py",
        "import subprocess\n\ndef test_run():\n    subprocess.run(['true'])\n",
    )
    _config(
        tmp_path,
        [
            {
                "name": "fixture",
                "roots": ["src"],
                "testRoots": ["tests"],
            }
        ],
    )

    snapshot, _ = build_atlas(tmp_path)

    assert snapshot.signals == []
    assert all(node.path != "tests/test_app.py" for node in snapshot.nodes if node.type == "operational-file")
