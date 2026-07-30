"""Contract and resolver evals for the machine-readable codebase atlas."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest
import yaml
from typer.testing import CliRunner

from sre_kb.atlas import build_atlas, check_atlas, write_atlas
from sre_kb.atlas.config import AtlasConfigError
from sre_kb.atlas.render import html_explorer
from sre_kb.cli import app


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _config(
    root: Path,
    projects: list[dict],
    *,
    overlays: dict | None = None,
    exclude: list[str] | None = None,
) -> None:
    data = {
        "apiVersion": "sre.kb/atlas-config/v1alpha1",
        "projects": projects,
        "exclude": exclude or [".work/**", "**/__pycache__/**"],
        "overlays": overlays or {},
        "output": {
            "path": "docs/codebase-atlas/generated",
            "maxDiagramNodes": 80,
            "html": True,
        },
    }
    _write(root / ".sre" / "atlas.yaml", yaml.safe_dump(data, sort_keys=False))


def test_python_graph_schema_and_drift_are_deterministic(tmp_path: Path):
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "fixture"\nversion = "1"\ndependencies = ["httpx>=1"]\n',
    )
    _write(tmp_path / "src" / "pkg" / "__init__.py", "from .a import run\n")
    _write(
        tmp_path / "src" / "pkg" / "a.py",
        "from . import b\nimport importlib\n\ndef run():\n    return importlib.import_module('plugin')\n",
    )
    _write(tmp_path / "src" / "pkg" / "b.py", "from . import a\n")
    _write(tmp_path / "tests" / "__init__.py", "")
    _write(tmp_path / "tests" / "test_a.py", "from pkg import a\n")
    _config(
        tmp_path,
        [
            {
                "name": "fixture",
                "roots": ["src"],
                "testRoots": ["tests"],
                "manifests": ["pyproject.toml"],
            }
        ],
    )

    snapshot, output = write_atlas(tmp_path)
    assert output == tmp_path / "docs" / "codebase-atlas" / "generated"
    assert any(edge.resolver == "python:ast" and edge.scope == "source" for edge in snapshot.edges)
    assert any(item.code == "resolver.python-dynamic-import" for item in snapshot.unknowns)
    assert any(
        cycle.granularity == "module" and len(cycle.members) == 2
        for cycle in snapshot.metrics.cycles
    )
    schema = json.loads((output / "CodebaseAtlas.schema.json").read_text(encoding="utf-8"))
    data = json.loads((output / "atlas.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    for name, expected_hash in manifest["files"].items():
        actual_hash = hashlib.sha256((output / name).read_bytes()).hexdigest()
        assert expected_hash == f"sha256:{actual_hash}"
    assert check_atlas(tmp_path).drifted is False

    with (tmp_path / "src" / "pkg" / "a.py").open("a", encoding="utf-8") as handle:
        handle.write("\n# changes the content digest\n")
    drift = check_atlas(tmp_path)
    assert "atlas.json" in drift.changed
    assert "manifest.json" in drift.changed


@pytest.mark.parametrize("unsafe_root", ["../outside", r"C:\outside"])
def test_boundary_rejects_parent_and_drive_paths(tmp_path: Path, unsafe_root: str):
    _config(
        tmp_path,
        [{"name": "escape", "roots": [unsafe_root], "manifests": []}],
    )
    with pytest.raises(AtlasConfigError, match="relative"):
        build_atlas(tmp_path)


def test_boundary_rejects_overlapping_source_and_test_roots(tmp_path: Path):
    _config(
        tmp_path,
        [
            {
                "name": "overlap",
                "roots": ["src"],
                "testRoots": ["src/tests"],
                "manifests": [],
            }
        ],
    )
    with pytest.raises(AtlasConfigError, match="overlap"):
        build_atlas(tmp_path)


def test_boundary_does_not_follow_a_configured_source_symlink(tmp_path: Path):
    outside = tmp_path / "real-source"
    _write(outside / "app.py", "")
    link = tmp_path / "linked-source"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"filesystem/account cannot create a symlink for this capability test: {exc}")
    _config(
        tmp_path,
        [{"name": "linked", "roots": ["linked-source"], "manifests": []}],
    )
    with pytest.raises(AtlasConfigError, match="symlink"):
        build_atlas(tmp_path)


def test_language_and_manifest_resolvers_use_structured_parsers(tmp_path: Path):
    _write(
        tmp_path / "java" / "pom.xml",
        """<project><dependencies><dependency><groupId>org.example</groupId>
<artifactId>client</artifactId><version>1.2</version></dependency></dependencies></project>""",
    )
    _write(
        tmp_path / "java" / "src" / "demo" / "A.java",
        "package demo; import demo.B; class A {}\n",
    )
    _write(tmp_path / "java" / "src" / "demo" / "B.java", "package demo; class B {}\n")
    _write(
        tmp_path / "web" / "package.json",
        '{"name":"web","dependencies":{"lodash":"^4"}}\n',
    )
    _write(
        tmp_path / "web" / "src" / "a.js",
        "import b from './b.js'; import _ from 'lodash';\n",
    )
    _write(tmp_path / "web" / "src" / "b.js", "export default 1;\n")
    _write(tmp_path / "web" / "src" / "later.ts", "import x from './b.js';\n")
    _write(
        tmp_path / "dotnet" / "app.csproj",
        '<Project><ItemGroup><PackageReference Include="Polly" Version="8.0" /></ItemGroup></Project>',
    )
    _write(
        tmp_path / "dotnet" / "A.cs",
        "using Demo.B;\nnamespace Demo.A;\nclass A {}\n",
    )
    _write(tmp_path / "dotnet" / "B.cs", "namespace Demo.B;\nclass B {}\n")
    _write(
        tmp_path / "go" / "go.mod",
        "module example.com/app\n\nrequire example.com/dep v1.2.3\n",
    )
    _write(
        tmp_path / "go" / "main.go",
        'package main\nimport "example.com/app/lib"\nfunc main() {}\n',
    )
    _write(tmp_path / "go" / "lib" / "lib.go", "package lib\n")
    _config(
        tmp_path,
        [
            {
                "name": "java",
                "roots": ["java/src"],
                "manifests": ["java/pom.xml"],
            },
            {
                "name": "web",
                "roots": ["web/src"],
                "manifests": ["web/package.json"],
            },
            {
                "name": "dotnet",
                "roots": ["dotnet"],
                "manifests": ["dotnet/app.csproj"],
            },
            {
                "name": "go",
                "roots": ["go"],
                "manifests": ["go/go.mod"],
            },
        ],
    )

    snapshot, _ = build_atlas(tmp_path)
    resolvers = {edge.resolver for edge in snapshot.edges}
    assert "java:tree-sitter" in resolvers
    assert "javascript:tree-sitter" in resolvers
    assert "javascript:tree-sitter+package-json" in resolvers
    assert "typescript:tree-sitter" in resolvers
    assert "csharp:tree-sitter" in resolvers
    assert "go:tree-sitter+go-mod" in resolvers
    assert "manifest:maven" in resolvers
    assert "manifest:nuget" in resolvers
    assert not snapshot.unknowns
    assert all("regex" not in edge.resolver for edge in snapshot.edges)


def test_node_typescript_lockfile_and_aliases_are_resolved(tmp_path: Path):
    _write(
        tmp_path / "web" / "package.json",
        json.dumps(
            {
                "name": "web",
                "private": True,
                "type": "module",
                "packageManager": "npm@11.1.0",
                "engines": {"node": ">=20"},
                "workspaces": ["packages/*"],
                "imports": {"#local": "./src/util.tsx"},
                "dependencies": {"express": "^4.18.0"},
            }
        ),
    )
    _write(
        tmp_path / "web" / "package-lock.json",
        json.dumps(
            {
                "name": "web",
                "lockfileVersion": 3,
                "packages": {
                    "": {
                        "name": "web",
                        "dependencies": {"express": "^4.18.0"},
                    },
                    "node_modules/express": {
                        "version": "4.18.3",
                        "dependencies": {"body-parser": "1.20.2"},
                    },
                    "node_modules/body-parser": {"version": "1.20.2"},
                },
            }
        ),
    )
    _write(
        tmp_path / "web" / "tsconfig.json",
        """{
  // TypeScript configuration files are JSON-with-comments.
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {"@app/*": ["src/*"],},
  },
}
""",
    )
    _write(
        tmp_path / "web" / "src" / "index.ts",
        "import express from 'express';\n"
        "import { value } from '@app/util';\n"
        "import { local } from '#local';\n"
        "import { readFile } from 'node:fs/promises';\n"
        "export const app = express();\n",
    )
    _write(
        tmp_path / "web" / "src" / "util.tsx",
        "export const value = <span>1</span>;\nexport const local = value;\n",
    )
    _config(
        tmp_path,
        [
            {
                "name": "web",
                "roots": ["web/src"],
                "manifests": [
                    "web/package.json",
                    "web/package-lock.json",
                    "web/tsconfig.json",
                ],
            }
        ],
    )

    snapshot, _ = build_atlas(tmp_path)
    project = next(node for node in snapshot.nodes if node.id == "project:web")
    assert project.annotations["nodeEngine"] == ">=20"
    assert project.annotations["packageManager"] == "npm@11.1.0"
    assert project.annotations["moduleType"] == "module"
    assert project.annotations["workspaces"] == ["packages/*"]

    express = next(
        node for node in snapshot.nodes if node.name == "express" and node.version == "4.18.3"
    )
    body_parser = next(
        node for node in snapshot.nodes if node.name == "body-parser" and node.version == "1.20.2"
    )
    resolvers = {edge.resolver for edge in snapshot.edges}
    assert "manifest:npm-lock" in resolvers
    assert "typescript:tree-sitter+package-lock" in resolvers
    assert "typescript:tree-sitter+tsconfig" in resolvers
    assert "typescript:tree-sitter+package-imports" in resolvers
    assert "typescript:tree-sitter+node-builtin" in resolvers
    assert any(
        edge.source == express.id and edge.target == body_parser.id and edge.kind == "depends-on"
        for edge in snapshot.edges
    )
    assert not any(item.code == "resolver.typescript-unavailable" for item in snapshot.unknowns)


def test_dotnet8_sdk_central_versions_and_nuget_lock_are_resolved(tmp_path: Path):
    _write(
        tmp_path / "dotnet" / "global.json",
        json.dumps(
            {
                "sdk": {
                    "version": "8.0.408",
                    "rollForward": "latestPatch",
                    "allowPrerelease": False,
                }
            }
        ),
    )
    _write(
        tmp_path / "dotnet" / "Directory.Packages.props",
        """<Project>
  <PropertyGroup>
    <ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally>
  </PropertyGroup>
  <ItemGroup>
    <PackageVersion Include="Polly" Version="8.4.2" />
  </ItemGroup>
</Project>
""",
    )
    _write(
        tmp_path / "dotnet" / "App" / "App.csproj",
        """<Project Sdk="Microsoft.NET.Sdk.Web">
  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Polly" />
    <ProjectReference Include="..\\Core\\Core.csproj" />
  </ItemGroup>
</Project>
""",
    )
    _write(
        tmp_path / "dotnet" / "Core" / "Core.csproj",
        """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net8.0</TargetFramework></PropertyGroup>
</Project>
""",
    )
    _write(
        tmp_path / "dotnet" / "App" / "packages.lock.json",
        json.dumps(
            {
                "version": 1,
                "dependencies": {
                    "net8.0": {
                        "Polly": {
                            "type": "Direct",
                            "requested": "[8.4.2, )",
                            "resolved": "8.4.2",
                            "dependencies": {"System.Memory": "4.5.5"},
                        },
                        "System.Memory": {
                            "type": "Transitive",
                            "resolved": "4.5.5",
                        },
                    }
                },
            }
        ),
    )
    _write(
        tmp_path / "dotnet" / "App" / "Program.cs",
        "using Core;\nvar builder = WebApplication.CreateBuilder(args);\n",
    )
    _write(tmp_path / "dotnet" / "Core" / "Core.cs", "namespace Core;\npublic class C {}\n")
    _config(
        tmp_path,
        [
            {
                "name": "dotnet-app",
                "roots": ["dotnet"],
                "manifests": [
                    "dotnet/global.json",
                    "dotnet/Directory.Packages.props",
                    "dotnet/App/App.csproj",
                    "dotnet/Core/Core.csproj",
                    "dotnet/App/packages.lock.json",
                ],
            }
        ],
    )

    snapshot, _ = build_atlas(tmp_path)
    project = next(node for node in snapshot.nodes if node.id == "project:dotnet-app")
    assert project.annotations["dotnetSdkVersion"] == "8.0.408"
    assert project.annotations["dotnetSdkRollForward"] == "latestPatch"
    assert project.annotations["targetFrameworks"] == ["net8.0"]
    assert project.annotations["projectSdks"] == [
        "Microsoft.NET.Sdk",
        "Microsoft.NET.Sdk.Web",
    ]

    polly = next(
        node for node in snapshot.nodes if node.name == "Polly" and node.version == "8.4.2"
    )
    memory = next(
        node for node in snapshot.nodes if node.name == "System.Memory" and node.version == "4.5.5"
    )
    assert "8.4.2" in polly.annotations["declaredVersions"]
    assert any(
        edge.source == polly.id
        and edge.target == memory.id
        and edge.resolver == "manifest:nuget-lock"
        for edge in snapshot.edges
    )
    assert any(
        edge.kind == "project-reference"
        and edge.resolver == "manifest:msbuild-declared"
        and edge.unresolved is False
        for edge in snapshot.edges
    )
    assert not snapshot.unknowns


def test_dotnet_project_assets_are_a_resolved_graph(tmp_path: Path):
    _write(tmp_path / "dotnet" / "Program.cs", 'Console.WriteLine("ok");\n')
    _write(
        tmp_path / "dotnet" / "project.assets.json",
        json.dumps(
            {
                "version": 3,
                "targets": {
                    "net8.0": {
                        "Direct.Package/1.2.3": {
                            "type": "package",
                            "dependencies": {"Transitive.Package": "2.0.0"},
                        },
                        "Transitive.Package/2.0.0": {"type": "package"},
                    }
                },
                "project": {
                    "frameworks": {
                        "net8.0": {
                            "dependencies": {
                                "Direct.Package": {
                                    "target": "Package",
                                    "version": "[1.2.3, )",
                                }
                            }
                        }
                    }
                },
            }
        ),
    )
    _config(
        tmp_path,
        [
            {
                "name": "dotnet",
                "roots": ["dotnet"],
                "manifests": ["dotnet/project.assets.json"],
            }
        ],
    )

    snapshot, _ = build_atlas(tmp_path)
    direct = next(node for node in snapshot.nodes if node.name == "Direct.Package")
    transitive = next(node for node in snapshot.nodes if node.name == "Transitive.Package")
    assert any(
        edge.source == "project:dotnet"
        and edge.target == direct.id
        and edge.resolver == "manifest:nuget-assets"
        for edge in snapshot.edges
    )
    assert any(
        edge.source == direct.id
        and edge.target == transitive.id
        and edge.resolver == "manifest:nuget-assets"
        for edge in snapshot.edges
    )


def test_msbuild_expressions_remain_explicit_unknowns(tmp_path: Path):
    _write(
        tmp_path / "dotnet" / "App.csproj",
        """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>$(TargetFramework)</TargetFramework>
  </PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="$(SharedProject)" />
  </ItemGroup>
</Project>
""",
    )
    _write(tmp_path / "dotnet" / "Program.cs", 'Console.WriteLine("ok");\n')
    _config(
        tmp_path,
        [
            {
                "name": "dotnet",
                "roots": ["dotnet"],
                "manifests": ["dotnet/App.csproj"],
            }
        ],
    )

    snapshot, _ = build_atlas(tmp_path)

    assert (
        sum(item.code == "resolver.msbuild-evaluation-required" for item in snapshot.unknowns) == 1
    )
    assert not any(edge.kind == "project-reference" for edge in snapshot.edges)
    project = next(node for node in snapshot.nodes if node.id == "project:dotnet")
    assert "targetFrameworks" not in project.annotations


def test_runtime_sbom_coverage_codeowners_and_html_are_evidence_backed(tmp_path: Path):
    _write(
        tmp_path / "pyproject.toml",
        '[project]\nname="fixture"\nversion="1"\ndependencies=["foo==1"]\n',
    )
    _write(tmp_path / "src" / "pkg" / "__init__.py", "")
    _write(tmp_path / "src" / "pkg" / "a.py", "import foo\n")
    _write(tmp_path / ".github" / "CODEOWNERS", "/src/pkg/** @team/pkg\n")
    _write(
        tmp_path / "evidence" / "runtime.json",
        json.dumps(
            {
                "apiVersion": "sre.kb/runtime-evidence/v1alpha1",
                "kind": "RuntimeEvidence",
                "nodes": [
                    {
                        "id": "service:api",
                        "name": "</script><img src=x>",
                        "type": "service",
                    },
                    {"id": "datastore:db", "name": "database", "type": "datastore"},
                ],
                "edges": [
                    {
                        "source": "service:api",
                        "target": "datastore:db",
                        "kind": "queries",
                        "sourceName": "otel-trace-export",
                        "observedAt": "2026-07-30T12:00:00Z",
                        "environment": "staging",
                        "evidenceRef": "trace-123",
                    }
                ],
            }
        ),
    )
    _write(
        tmp_path / "evidence" / "bom.json",
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "version": 1,
                "components": [
                    {
                        "type": "library",
                        "bom-ref": "pkg:pypi/foo@1",
                        "name": "foo",
                        "version": "1",
                        "purl": "pkg:pypi/foo@1",
                        "licenses": [{"license": {"id": "MIT"}}],
                    },
                    {
                        "type": "library",
                        "bom-ref": "pkg:pypi/bar@2",
                        "name": "bar",
                        "version": "2",
                        "purl": "pkg:pypi/bar@2",
                    },
                ],
                "dependencies": [{"ref": "pkg:pypi/foo@1", "dependsOn": ["pkg:pypi/bar@2"]}],
            }
        ),
    )
    _write(
        tmp_path / "evidence" / "coverage.xml",
        '<coverage><packages><package><classes><class filename="src/pkg/a.py" '
        'line-rate="0.75" /></classes></package></packages></coverage>',
    )
    _config(
        tmp_path,
        [
            {
                "name": "fixture",
                "roots": ["src"],
                "manifests": ["pyproject.toml"],
            }
        ],
        overlays={
            "runtimeEvidence": ["evidence/runtime.json"],
            "sbom": ["evidence/bom.json"],
            "coverage": ["evidence/coverage.xml"],
            "codeowners": [".github/CODEOWNERS"],
            "changeHistory": False,
        },
    )

    snapshot, _ = build_atlas(tmp_path)
    assert any(edge.scope == "runtime" and edge.kind == "queries" for edge in snapshot.edges)
    assert any(edge.scope == "sbom" and edge.kind == "depends-on" for edge in snapshot.edges)
    source = next(node for node in snapshot.nodes if node.path == "src/pkg/a.py")
    assert source.coverage == 0.75
    assert source.owners == ["@team/pkg"]
    # The declared distribution and unresolved Python import stay separate: Python import names
    # are not guaranteed to equal distribution names.
    foo = next(item for item in snapshot.licenses if item.node == "package:pypi:foo")
    assert foo.licenses == ["MIT"]
    assert foo.status == "DECLARED"
    page = html_explorer(snapshot)
    assert "</script><img src=x>" not in page
    assert "\\u003c/script\\u003e\\u003cimg src=x\\u003e" in page


def test_history_overlay_uses_fixed_argv_and_annotates_exact_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _write(tmp_path / "src" / "app.py", "print('ok')\n")
    _config(
        tmp_path,
        [{"name": "fixture", "roots": ["src"], "manifests": []}],
    )
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 30
        return SimpleNamespace(stdout=b"src/app.py\0src/app.py\0")

    monkeypatch.setattr("sre_kb.atlas.overlays.shutil.which", lambda _: "git")
    monkeypatch.setattr("sre_kb.atlas.overlays.subprocess.run", fake_run)
    snapshot, _ = build_atlas(tmp_path, include_history=True)
    node = next(item for item in snapshot.nodes if item.path == "src/app.py")
    assert node.changes == 2
    assert calls[0][0] == "git"
    assert "--name-only" in calls[0]


def test_xml_entity_declarations_are_rejected(tmp_path: Path):
    _write(tmp_path / "src" / "app.py", "")
    _write(
        tmp_path / "coverage.xml",
        '<!DOCTYPE x [<!ENTITY x "boom">]><coverage>&x;</coverage>',
    )
    _config(
        tmp_path,
        [{"name": "fixture", "roots": ["src"], "manifests": []}],
        overlays={"coverage": ["coverage.xml"]},
    )
    snapshot, _ = build_atlas(tmp_path)
    assert any(item.code == "overlay.coverage-invalid" for item in snapshot.unknowns)


def test_cli_generates_then_reports_drift(tmp_path: Path):
    _write(tmp_path / "src" / "app.py", "")
    _config(
        tmp_path,
        [{"name": "fixture", "roots": ["src"], "manifests": []}],
    )
    runner = CliRunner()
    generated = runner.invoke(app, ["atlas", "--target", str(tmp_path)])
    assert generated.exit_code == 0, generated.output
    clean = runner.invoke(app, ["atlas-check", "--target", str(tmp_path)])
    assert clean.exit_code == 0, clean.output
    _write(tmp_path / "src" / "app.py", "print('drift')\n")
    drifted = runner.invoke(app, ["atlas-check", "--target", str(tmp_path)])
    assert drifted.exit_code == 1
    report = json.loads((tmp_path / ".work" / "atlas-drift.json").read_text(encoding="utf-8"))
    assert report["drifted"] is True


def test_regeneration_removes_only_files_owned_by_the_prior_manifest(tmp_path: Path):
    _write(tmp_path / "src" / "app.py", "")
    _config(
        tmp_path,
        [{"name": "fixture", "roots": ["src"], "manifests": []}],
    )
    _, output = write_atlas(tmp_path)
    assert (output / "atlas.html").is_file()
    unrelated = output / "maintainer-note.txt"
    _write(unrelated, "keep\n")

    config_path = tmp_path / ".sre" / "atlas.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["output"]["html"] = False
    _write(config_path, yaml.safe_dump(config, sort_keys=False))
    write_atlas(tmp_path)

    assert not (output / "atlas.html").exists()
    assert unrelated.read_text(encoding="utf-8") == "keep\n"
    drift = check_atlas(tmp_path)
    assert drift.removed == ("maintainer-note.txt",)
