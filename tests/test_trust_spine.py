"""Phase 2 — status-aware trust spine: a verified artifact must not rest on unverified
foundations (crossref downgrade), and evidence paths can't escape the repo root.
"""

from __future__ import annotations

from sre_kb.collectors.base import hash_excerpt
from sre_kb.validation.crossref import status_aware_downgrades
from sre_kb.validation.provenance import verify_evidence

_HASH = "sha256:" + "0" * 64


def _ref(kind: str, name: str, relation: str = "depends-on") -> dict:
    return {"kind": kind, "name": name, "relation": relation}


# --- status-aware crossref -------------------------------------------------------------


def test_downgrade_when_depending_on_non_verified() -> None:
    status = {"Flow/f": "verified", "Fallback/b": "needs-review"}
    refs = {"Flow/f": [_ref("Fallback", "b")], "Fallback/b": []}
    down = status_aware_downgrades(status, refs)
    assert "Flow/f" in down and "Fallback/b" in down["Flow/f"]


def test_downgrade_cascades_to_a_fixpoint() -> None:
    # A depends-on B depends-on C(needs-review): C taints B, then B taints A.
    status = {"A/a": "verified", "B/b": "verified", "C/c": "needs-review"}
    refs = {"A/a": [_ref("B", "b")], "B/b": [_ref("C", "c")], "C/c": []}
    assert set(status_aware_downgrades(status, refs)) == {"A/a", "B/b"}


def test_backlink_relations_do_not_downgrade() -> None:
    # An alert/runbook needing review does not make the flow it watches unverified.
    status = {"Flow/f": "verified", "Alert/a": "needs-review", "Runbook/r": "needs-review"}
    refs = {"Flow/f": [_ref("Alert", "a", "alerts-on"), _ref("Runbook", "r", "covers")]}
    assert status_aware_downgrades(status, refs) == {}


def test_missing_dependency_referent_downgrades() -> None:
    assert "A/a" in status_aware_downgrades({"A/a": "verified"}, {"A/a": [_ref("B", "gone")]})


# --- provenance path confinement -------------------------------------------------------


def _doc(path: str, excerpt_hash: str = _HASH) -> dict:
    return {"evidence": [{"path": path, "lines": {"start": 1, "end": 1}, "excerptHash": excerpt_hash}]}


def test_provenance_rejects_path_escape(tmp_path) -> None:
    assert any("escapes repo root" in e for e in verify_evidence(_doc("/etc/passwd"), tmp_path))
    assert any("escapes repo root" in e for e in verify_evidence(_doc("../secret.txt"), tmp_path))


def test_provenance_allows_in_root_path(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    doc = _doc("a.txt", hash_excerpt(["x\n"], 1, 1))
    assert verify_evidence(doc, tmp_path) == []   # in-root + hash matches -> clean


def test_provenance_rejects_inverted_range(tmp_path) -> None:
    """An inverted range (start>end) hashes an empty slice and must be flagged as out-of-bounds, not
    silently 'verified' against the empty-excerpt hash."""
    (tmp_path / "a.txt").write_text("x\ny\n", encoding="utf-8")
    doc = {"evidence": [{"path": "a.txt", "lines": {"start": 2, "end": 1}, "excerptHash": _HASH}]}
    assert any("out of bounds" in e for e in verify_evidence(doc, tmp_path))


# --- status-aware readiness ------------------------------------------------------------


def test_readiness_credits_only_verified_artifacts() -> None:
    from sre_kb.models.facts import FactSet
    from sre_kb.scoring.readiness import readiness_spec

    fs = FactSet()
    verified = [{"kind": "Runbook", "status": "verified", "spec": {}},
                {"kind": "Alert", "status": "verified", "spec": {"alertType": "burn-rate"}}]
    drafts = [{"kind": "Runbook", "status": "needs-review", "spec": {}},
              {"kind": "Alert", "status": "needs-review", "spec": {"alertType": "burn-rate"}}]
    sv, snr = readiness_spec(fs, verified, []), readiness_spec(fs, drafts, [])

    assert sv["prrChecks"]["runbook-for-top-flow"] is True
    assert snr["prrChecks"]["runbook-for-top-flow"] is False    # a draft doesn't count
    assert sv["score"] > snr["score"]                           # verified coverage scores higher
    assert any("not yet verified" in g for g in snr["gaps"])    # present-but-draft is noted, not hidden
