"""Supply-chain hardening config guards (HYBRID-PLAN R8).

These don't run the CI gates (that's CI's job); they keep the checked-in artifacts well-formed and
the gates wired, so a future edit can't silently drop a supply-chain control.
"""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent.parent


def test_requirements_lock_is_fully_hashed():
    """Every pinned dependency carries a sha256 hash — a --require-hashes install is tamper-evident."""
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    pins = [ln for ln in lock.splitlines() if "==" in ln and not ln.lstrip().startswith("#")]
    assert pins, "lockfile has no pinned requirements"
    assert "--hash=sha256:" in lock
    # each pinned line opens a hash continuation (`name==x \`), so none is unhashed
    assert all(ln.rstrip().endswith("\\") for ln in pins), "an unhashed pin slipped into the lockfile"


def test_secrets_baseline_is_valid():
    baseline = json.loads((ROOT / ".secrets.baseline").read_text(encoding="utf-8"))
    assert baseline.get("version") and "results" in baseline


def test_renovate_pins_action_digests():
    cfg = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
    assert "helpers:pinGitHubActionDigests" in cfg.get("extends", [])
    assert any(r.get("pinDigests") for r in cfg.get("packageRules", []))


def test_ci_wires_both_supply_chain_gates():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pip install --require-hashes -r requirements.lock" in ci  # hashed lockfile gate
    assert "detect-secrets-hook --baseline .secrets.baseline" in ci    # second secret gate


def test_structural_search_dependencies_are_mit_reviewed_and_not_a_daemon():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = "\n".join(project["project"]["dependencies"]).lower()
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    sbom = json.loads(
        (ROOT / "evidence" / "structural-search.cdx.json").read_text(encoding="utf-8")
    )

    expected = {
        "ast-grep-py",
        "tree-sitter-bash",
        "tree-sitter-sql",
        "tree-sitter-yaml",
    }
    assert expected <= {name for name in expected if name in dependencies}
    assert "tree-sitter-dockerfile" not in dependencies
    assert expected <= {component["name"] for component in sbom["components"]}
    assert all(
        component["licenses"] == [{"license": {"id": "MIT"}}]
        for component in sbom["components"]
    )
    assert all(name in notices for name in expected)
    assert "in-process" in notices
