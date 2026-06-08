"""Supply-chain hardening config guards (HYBRID-PLAN R8).

These don't run the CI gates (that's CI's job); they keep the checked-in artifacts well-formed and
the gates wired, so a future edit can't silently drop a supply-chain control.
"""

from __future__ import annotations

import json
from pathlib import Path

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
