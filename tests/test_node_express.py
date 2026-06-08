"""Node.js collector — breadth to a fourth stack (after Java/Spring, .NET/Steeltoe, Python/FastAPI).

Proves the same engine extracts byte-grounded tech-stack facts from a `package.json` and the
*unchanged* scaffolder turns them into a validated `TechStack` — repo-neutrality beyond the JVM/CLR
and Python, with no new dependency (direct JSON parse).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.node_express import package_json
from sre_kb.pipeline import run as run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample-node-express"


def _facts():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-node-express", commit=LOCAL_COMMIT)
    return scan(ctx), ctx


# --------------------------------------------------------------- collector facts

def test_tech_stack_facts_are_node():
    fs, _ = _facts()
    fw = fs.first("tech.framework")
    rt = fs.first("tech.runtime")
    assert fw and fw.attrs["name"] == "express"
    assert rt and rt.attrs["language"] == "javascript"
    assert rt.attrs["runtime"] == "node" and rt.attrs["buildTool"] == "npm"


def test_runtime_dependencies_are_extracted_with_provenance():
    fs, _ = _facts()
    deps = {f.attrs["name"] for f in fs.of("tech.dependency")}
    assert {"express", "pg", "axios", "pino"} <= deps
    # devDependencies are not production posture — they must not leak in
    assert "jest" not in deps and "eslint" not in deps
    for f in fs.of("tech.dependency"):
        assert f.evidence.path.endswith("package.json") and f.evidence.source_tier == "ast"


def test_nest_resolves_before_a_platform_adapter():
    """Framework table is most-specific-first: a Nest app that also lists express is `nestjs`."""
    assert package_json._framework({"express": "4", "@nestjs/core": "10"}) == ("@nestjs/core", "nestjs")


def test_self_gating_on_a_non_node_repo():
    spring = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
    ctx = ScanContext(root=spring, repo="file://spring", commit=LOCAL_COMMIT)
    assert package_json.collect(ctx) == []  # no package.json -> nothing


def test_malformed_package_json_yields_a_grounded_parse_error(tmp_path):
    (tmp_path / "package.json").write_text("{ not valid json", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x", commit=LOCAL_COMMIT)
    facts = package_json.collect(ctx)
    assert any(f.type == "collector.parse_error" for f in facts)  # gap recorded, not swallowed


# --------------------------------------------------------------- end-to-end KB

def test_node_service_yields_a_validated_tech_stack(tmp_path):
    r = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="node", to_stage="validate")
    docs = {}
    for sub in ("kb/verified", "kb/needs-review"):
        for p in (r.root / sub).rglob("*.yaml"):
            d = yaml.safe_load(p.read_text())
            docs[(d["kind"], d["metadata"]["name"])] = d

    ts = next(d for (kind, _), d in docs.items() if kind == "TechStack")
    assert ts["spec"]["languages"] == ["javascript"]
    assert ts["spec"]["runtime"] == "node" and ts["spec"]["buildTool"] == "npm"
    assert {"name": "express"} in ts["spec"]["frameworks"]
    assert {"express", "pg", "axios"} <= set(ts["spec"]["notableLibraries"])

    from sre_kb.validation import validate_kb_tree
    bad = [x for x in validate_kb_tree(r.root / "kb") if not x.ok]
    assert not bad, [(x.path, x.errors) for x in bad]
