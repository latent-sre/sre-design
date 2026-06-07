"""Phase 2 — the trust spine is status-aware.

Three holes the deep review found (HYBRID-PLAN.md §4 "Gates not status-aware"):
  - crossref resolved a reference if ANY artifact with that name existed, regardless of
    status — so a verified artifact could depend on an unverified one;
  - readiness counted artifacts by kind, not status — a graph could grade 'A' on
    needs-review controls;
  - provenance had no path confinement — an edited/LLM-sourced citation could point
    outside the scanned repo.
"""

from __future__ import annotations

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext, hash_excerpt
from sre_kb.models.facts import FactSet
from sre_kb.scoring.readiness import readiness_spec
from sre_kb.validation.crossref import check_crossrefs, resolve_statuses
from sre_kb.validation.provenance import verify_evidence


def _doc(kind, name, status, crossrefs=None):
    return {
        "kind": kind,
        "metadata": {"name": name},
        "status": status,
        "crossRefs": crossrefs or [],
    }


# ----------------------------------------------------------------- status-aware crossref

def test_existence_only_when_no_status_map():
    docs = [_doc("Flow", "f", "verified", [{"kind": "Alert", "name": "a", "relation": "depends-on"}])]
    # back-compatible: without a status map, only dangling references are flagged.
    assert "Flow/f" in check_crossrefs(docs)
    docs.append(_doc("Alert", "a", "needs-review"))
    assert check_crossrefs(docs) == {}  # resolves on existence alone


def test_verified_cannot_depend_on_unverified():
    docs = [
        _doc("Flow", "f", "verified", [{"kind": "ResiliencyGap", "name": "g", "relation": "depends-on"}]),
        _doc("ResiliencyGap", "g", "needs-review"),
    ]
    status = {("Flow", "f"): "verified", ("ResiliencyGap", "g"): "needs-review"}
    problems = resolve_statuses(docs, status)
    assert status[("Flow", "f")] == "needs-review"  # downgraded
    assert any("unverified referent" in e for e in problems["Flow/f"])


def test_informational_relation_does_not_downgrade():
    # alerts-on / covers / emits / mitigates are reverse/informational links: a verified Flow
    # may 'alerts-on' a needs-review Alert without inheriting its uncertainty.
    docs = [
        _doc("Flow", "f", "verified", [{"kind": "Alert", "name": "a", "relation": "alerts-on"}]),
        _doc("Alert", "a", "needs-review"),
    ]
    status = {("Flow", "f"): "verified", ("Alert", "a"): "needs-review"}
    problems = resolve_statuses(docs, status)
    assert status[("Flow", "f")] == "verified"
    assert problems == {}


def test_downgrade_cascades_to_fixpoint():
    # A (verified) -depends-on-> B (verified) -depends-on-> C (needs-review).
    # C unverifies B, then the now-unverified B must unverify A.
    docs = [
        _doc("Flow", "a", "verified", [{"kind": "Flow", "name": "b", "relation": "depends-on"}]),
        _doc("Flow", "b", "verified", [{"kind": "Dependency", "name": "c", "relation": "depends-on"}]),
        _doc("Dependency", "c", "needs-review"),
    ]
    status = {("Flow", "a"): "verified", ("Flow", "b"): "verified", ("Dependency", "c"): "needs-review"}
    resolve_statuses(docs, status)
    assert status[("Flow", "a")] == "needs-review"
    assert status[("Flow", "b")] == "needs-review"


def test_dangling_trust_ref_also_downgrades():
    docs = [_doc("Flow", "f", "verified", [{"kind": "Fallback", "name": "missing", "relation": "depends-on"}])]
    status = {("Flow", "f"): "verified"}
    resolve_statuses(docs, status)
    assert status[("Flow", "f")] == "needs-review"


# ----------------------------------------------------------------- status-aware readiness

def test_readiness_does_not_credit_unverified_controls():
    fs = FactSet()
    burn = {"kind": "Alert", "status": "verified", "spec": {"alertType": "burn-rate"}}
    draft_runbook = {"kind": "Runbook", "status": "needs-review", "spec": {}}
    spec = readiness_spec(fs, [burn, draft_runbook], [])
    assert spec["prrChecks"]["burn-rate-alert"] is True            # verified -> credited
    assert spec["prrChecks"]["runbook-for-top-flow"] is False      # needs-review -> not credited
    assert any("Runbook exists but is not verified" in g for g in spec["gaps"])


def test_readiness_unverified_alert_is_a_gap_not_a_pass():
    fs = FactSet()
    draft_alert = {"kind": "Alert", "status": "needs-review", "spec": {"alertType": "threshold"}}
    spec = readiness_spec(fs, [draft_alert], [])
    assert spec["prrChecks"]["alert-for-top-flow"] is False
    assert any("Alert exists but is not verified" in g for g in spec["gaps"])


# ----------------------------------------------------------------- provenance path confinement

def test_provenance_rejects_path_escaping_repo_root(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "A.java").write_text("class A {}\n", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret\n", encoding="utf-8")

    # A citation that hash-matches bytes OUTSIDE the repo must be rejected on confinement,
    # before the hash is ever trusted.
    escaping = {"evidence": [{
        "repo": "r", "commit": LOCAL_COMMIT[:7], "path": "../secret.txt",
        "lines": {"start": 1, "end": 1},
        "excerptHash": hash_excerpt(["top secret\n"], 1, 1), "detector": "x",
    }]}
    errs = verify_evidence(escaping, root)
    assert errs and "escapes repo root" in errs[0]


def test_provenance_still_accepts_in_root_citation(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "A.java").write_text("class A {}\n", encoding="utf-8")
    ctx = ScanContext(root=root, repo="r", commit=LOCAL_COMMIT)
    ev = ctx.evidence("src/A.java", 1, 1, "x")
    doc = {"evidence": [ev.model_dump(mode="json")]}
    assert verify_evidence(doc, root) == []
