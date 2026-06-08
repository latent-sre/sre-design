"""Criticality reliability spine (HYBRID-PLAN Round-3 R1-R3, adopted from resiliency-skills).

R1 a `Criticality` kind grounded to a declaration + PII/PCI signatures; R2 a deterministic alert
severity floor by tier (only a *grounded* tier raises severity); R3 the Tier-B proposal path
(`.sre/criticality-proposal.yaml`) that lands needs-review and never feeds the floor.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from sre_kb.collectors import criticality
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.pipeline import run as run_pipeline
from sre_kb.render.alerts import effective_severity

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


# --------------------------------------------------------------------------- R2: the floor (unit)


@pytest.mark.parametrize(
    "declared,tier,expected",
    [
        ("high", "tier0", "critical"),  # tier-0 raises the default high to a page
        ("high", "tier1", "high"),  # already at/above the floor -> unchanged
        ("high", "tier2", "high"),  # floor (medium) is below high -> unchanged
        ("medium", "tier1", "high"),  # raised up to the tier floor
        ("low", "tier0", "critical"),  # raised all the way
        ("critical", "tier3", "critical"),  # never LOWERED below a declared severity
        ("high", None, "high"),  # unscored service -> no-op
        ("high", "unknown", "high"),  # unknown tier -> no-op
        ("bogus", "tier1", "high"),  # unrankable declared sorts last -> floored, not slipped past
    ],
)
def test_effective_severity_floors_up_only(declared, tier, expected):
    assert effective_severity(declared, tier) == expected


def test_malformed_declaration_emits_a_parse_error_fact(tmp_path):
    """A broken .sre/criticality.yaml is surfaced as a collector.parse_error fact, not silently
    ignored."""
    from sre_kb.collectors.base import ScanContext

    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "criticality.yaml").write_text("tier: : oops\n", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")

    errs = [f for f in criticality.collect(ctx) if f.type == "collector.parse_error"]
    assert len(errs) == 1 and errs[0].attrs["detector"] == "common.criticality"


# --------------------------------------------------------------------------- R1: the collector


def _ctx(root: Path) -> ScanContext:
    return ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)


def test_collector_grounds_declaration_and_detects_pii_pci(tmp_path):
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "criticality.yaml").write_text(
        "tier: tier0\nbusinessCriticality: critical\nsource: catalog\n", encoding="utf-8"
    )
    (tmp_path / "Order.java").write_text(
        "class Order {\n  String email;\n  String cardNumber;\n}\n", encoding="utf-8"
    )
    facts = criticality.collect(_ctx(tmp_path))
    declared = [f for f in facts if f.type == "criticality.declared"]
    classes = {f.attrs["classification"] for f in facts if f.type == "criticality.dataclass"}
    assert len(declared) == 1
    assert declared[0].attrs["tier"] == "tier0"
    assert declared[0].evidence.source_tier == "ast"  # authoritative declaration -> Tier-A
    assert classes == {"pii", "pci"}  # re-derived deterministically


def test_collector_is_inert_without_declaration_or_signals(tmp_path):
    (tmp_path / "Plain.java").write_text("class Plain { int qty; }\n", encoding="utf-8")
    assert criticality.collect(_ctx(tmp_path)) == []


def test_proposal_is_tier_b_and_catalog_wins_over_proposal(tmp_path):
    (tmp_path / ".sre").mkdir()
    (tmp_path / ".sre" / "criticality-proposal.yaml").write_text(
        "tier: tier1\nsource: inferred\n", encoding="utf-8"
    )
    only_proposal = criticality.collect(_ctx(tmp_path))
    decl = next(f for f in only_proposal if f.type == "criticality.declared")
    assert decl.evidence.source_tier == "llm" and decl.attrs["tier"] == "tier1"

    # An authoritative declaration beats the proposal (never read both).
    (tmp_path / ".sre" / "criticality.yaml").write_text(
        "tier: tier0\nsource: catalog\n", encoding="utf-8"
    )
    decl2 = next(f for f in criticality.collect(_ctx(tmp_path)) if f.type == "criticality.declared")
    assert decl2.evidence.source_tier == "ast" and decl2.attrs["tier"] == "tier0"


# --------------------------------------------------------------------------- R1+R2 end-to-end


def _kb_docs(root: Path) -> list[dict]:
    return [yaml.safe_load(p.read_text()) for p in (root / "kb").rglob("*.yaml")]


def _run_copy(tmp_path, files: dict[str, str], run_id: str) -> list[dict]:
    target = tmp_path / run_id
    shutil.copytree(FIXTURE, target)
    for rel, content in files.items():
        fp = target / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    res = run_pipeline(
        str(target), work_root=str(tmp_path / f"w-{run_id}"), run_id=run_id, to_stage="validate"
    )
    return _kb_docs(res.root)


def _burn_alert(docs: list[dict]) -> dict:
    return next(d for d in docs if d["kind"] == "Alert" and d["spec"]["alertType"] == "burn-rate")


def test_grounded_tier0_floors_the_burn_rate_alert_to_critical(tmp_path):
    # Baseline: no declaration -> the burn-rate alert keeps its declared "high".
    base = _run_copy(tmp_path, {}, "base")
    assert _burn_alert(base)["spec"]["severity"] == "high"
    assert not [d for d in base if d["kind"] == "Criticality"]  # inert without a declaration

    # tier-0 declared authoritatively -> Criticality verified + the alert is floored to critical.
    crit = _run_copy(tmp_path, {".sre/criticality.yaml": "tier: tier0\nsource: catalog\n"}, "t0")
    crit_doc = next(d for d in crit if d["kind"] == "Criticality")
    assert crit_doc["status"] == "verified" and crit_doc["spec"]["tier"] == "tier0"
    assert crit_doc["evidence"][0]["source_tier"] == "ast"
    assert _burn_alert(crit)["spec"]["severity"] == "critical"


def test_proposed_tier_is_needs_review_and_does_not_floor(tmp_path):
    # A Tier-B proposal must NOT amplify paging: the alert stays "high", and the Criticality
    # artifact lands needs-review / LLM-tier for a human to confirm.
    docs = _run_copy(
        tmp_path, {".sre/criticality-proposal.yaml": "tier: tier0\nsource: inferred\n"}, "prop"
    )
    crit_doc = next(d for d in docs if d["kind"] == "Criticality")
    assert crit_doc["status"] == "needs-review"
    assert crit_doc["evidence"][0]["source_tier"] == "llm"
    assert _burn_alert(docs)["spec"]["severity"] == "high"  # proposed tier does NOT feed the floor
