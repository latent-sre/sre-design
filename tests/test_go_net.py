"""Go collector — breadth to a fifth stack (after Java/Spring, .NET/Steeltoe, Python/FastAPI, Node).

Proves the same engine extracts byte-grounded tech-stack facts from a `go.mod` and the *unchanged*
scaffolder turns them into a validated `TechStack`, with no new dependency (direct parse).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.go_net import go_mod
from sre_kb.pipeline import run as run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample-go-gin"


def _facts():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-go-gin", commit=LOCAL_COMMIT)
    return scan(ctx), ctx


# --------------------------------------------------------------- collector facts

def test_tech_stack_facts_are_go():
    fs, _ = _facts()
    fw = fs.first("tech.framework")
    rt = fs.first("tech.runtime")
    assert fw and fw.attrs["name"] == "gin"
    assert rt and rt.attrs["language"] == "go"
    assert rt.attrs["runtime"] == "go" and rt.attrs["buildTool"] == "gomod"


def test_direct_requires_extracted_indirect_skipped_with_provenance():
    fs, _ = _facts()
    deps = {f.attrs["name"] for f in fs.of("tech.dependency")}
    assert "github.com/gin-gonic/gin" in deps
    assert "github.com/jackc/pgx/v5" in deps and "github.com/redis/go-redis/v9" in deps
    # `// indirect` (transitive) requires are not the service's declared posture
    assert "golang.org/x/sys" not in deps and "github.com/bytedance/sonic" not in deps
    for f in fs.of("tech.dependency"):
        assert f.evidence.path.endswith("go.mod") and f.evidence.source_tier == "ast"


def test_single_line_require_form_is_parsed():
    lines = ["module x\n", "go 1.22\n", "require github.com/go-chi/chi/v5 v5.0.11\n"]
    assert go_mod._direct_requires(lines) == [("github.com/go-chi/chi/v5", 3)]


def test_self_gating_on_a_non_go_repo():
    spring = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
    ctx = ScanContext(root=spring, repo="file://spring", commit=LOCAL_COMMIT)
    assert go_mod.collect(ctx) == []  # no go.mod -> nothing


# --------------------------------------------------------------- end-to-end KB

def test_go_service_yields_a_validated_tech_stack(tmp_path):
    r = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="go", to_stage="validate")
    docs = {}
    for sub in ("kb/verified", "kb/needs-review"):
        for p in (r.root / sub).rglob("*.yaml"):
            d = yaml.safe_load(p.read_text())
            docs[(d["kind"], d["metadata"]["name"])] = d

    ts = next(d for (kind, _), d in docs.items() if kind == "TechStack")
    assert ts["spec"]["languages"] == ["go"]
    assert ts["spec"]["runtime"] == "go" and ts["spec"]["buildTool"] == "gomod"
    assert {"name": "gin"} in ts["spec"]["frameworks"]
    assert "github.com/gin-gonic/gin" in ts["spec"]["notableLibraries"]

    from sre_kb.validation import validate_kb_tree
    bad = [x for x in validate_kb_tree(r.root / "kb") if not x.ok]
    assert not bad, [(x.path, x.errors) for x in bad]
