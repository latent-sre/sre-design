"""Coverage discovery (the production-run finding): the deterministic blind-spot ledger,
the area re-grounding contract (locate / refute-by-fact-set / route), and the engine-
recommendation flywheel."""

from __future__ import annotations

import json
from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.pipeline.areas import (
    PROPOSALS_REL,
    AreaProposal,
    apply_areas,
    covered_paths,
    run_discover_areas,
)
from sre_kb.reporting.coverage import coverage_report


def _repo(tmp_path: Path) -> Path:
    """A target with one covered file (manifest) and two uncovered blind spots."""
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: orders\n", encoding="utf-8")
    mig = tmp_path / "db" / "migration"
    mig.mkdir(parents=True)
    (mig / "V7__drop_index.sql").write_text(
        "-- destructive change shipped without a rollback\n"
        "DROP INDEX idx_orders_customer;\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM eclipse-temurin:21\nUSER root\n", encoding="utf-8")
    return tmp_path


def test_coverage_report_ledgers_walked_vs_cited(tmp_path):
    root = _repo(tmp_path)
    ctx = ScanContext(root=root, repo="file://x")
    fs = scan(ctx)
    report = coverage_report(ctx, fs, [])
    assert report["filesWalked"] == 3 and report["filesCovered"] == 1  # only the manifest cited
    groups = {g["group"]: g for g in report["uncovered"]["groups"]}
    assert groups["*.sql"]["count"] == 1
    assert groups["Dockerfile"]["count"] == 1
    assert "db/migration/V7__drop_index.sql" in groups["*.sql"]["samples"]
    assert "Topology" in report["kindsNeverEmitted"]  # no docs passed
    assert "common.manifest_pcf" in report["detectorsFired"]


def test_area_regrounding_locates_refutes_and_routes(tmp_path):
    root = _repo(tmp_path)
    ctx = ScanContext(root=root, repo="file://x")
    covered = {"manifest.yml"}
    result = apply_areas(ctx, [
        AreaProposal("db-migrations", "DROP INDEX idx_orders_customer;",
                     ("db/migration/V7__drop_index.sql",), "destructive DDL unreviewed",
                     "parse migration files into a schema-change fact"),
        AreaProposal("pcf-manifests", "applications:", ("manifest.yml",)),   # already covered
        AreaProposal("ghost-area", "this line exists nowhere"),              # unlocatable
        AreaProposal("Bad Name!", "DROP INDEX idx_orders_customer;"),        # not kebab-case
    ], covered)
    by = {o.proposal.name: o for o in result.outcomes}
    assert by["db-migrations"].result == "routed"
    assert by["db-migrations"].path == "db/migration/V7__drop_index.sql"
    assert by["pcf-manifests"].result == "refuted"
    assert "already collects" in by["pcf-manifests"].note
    assert by["ghost-area"].result == "unlocatable"
    assert by["Bad Name!"].result == "invalid-name"


def test_run_discover_areas_writes_engine_recommendations(tmp_path):
    root = _repo(tmp_path)
    (root / ".sre").mkdir()
    (root / PROPOSALS_REL).write_text(json.dumps({"areas": [
        {"name": "db-migrations", "files": ["db/migration/V7__drop_index.sql"],
         "evidence": "DROP INDEX idx_orders_customer;",
         "missing": "destructive DDL ships with no rollback or review trail",
         "proposal": "collect schema.migration facts from db/migration/*.sql"},
    ]}), encoding="utf-8")
    facts = tmp_path / "facts.jsonl"
    facts.write_text(json.dumps({"type": "pcf.app", "attrs": {},
                                 "evidence": {"path": "manifest.yml"}}) + "\n", encoding="utf-8")
    reports = tmp_path / "reports"
    result = run_discover_areas(str(root), facts, reports)
    assert len(result.kept()) == 1
    recs = json.loads((reports / "engine-recommendations.json").read_text())
    [rec] = recs["recommendations"]
    assert rec["area"] == "area-db-migrations"
    assert rec["anchor"].startswith("db/migration/V7__drop_index.sql:")
    assert rec["source"] == "llm" and rec["advisory"] is True
    md = (reports / "engine-recommendations.md").read_text()
    assert "area-db-migrations" in md and "confirm-gap area-<name> --novel" in md


def test_covered_paths_reads_the_fact_ledger(tmp_path):
    facts = tmp_path / "facts.jsonl"
    facts.write_text(
        json.dumps({"type": "a", "evidence": {"path": "x.java"}}) + "\n"
        + "not json\n"
        + json.dumps({"type": "b", "evidence": {"path": "y.yml"}}) + "\n", encoding="utf-8")
    assert covered_paths(facts) == {"x.java", "y.yml"}
    assert covered_paths(tmp_path / "absent.jsonl") == set()


def test_run_emits_the_coverage_ledger_and_gates_the_worklist_task(tmp_path):
    from sre_kb.pipeline import run as run_pipeline

    (tmp_path / "target").mkdir()
    root = _repo(tmp_path / "target")
    r = run_pipeline(str(root), work_root=str(tmp_path / "w"), run_id="cov",
                     to_stage="validate")
    coverage = json.loads((r.root / "reports" / "coverage.json").read_text())
    assert coverage["uncovered"]["count"] >= 2
    worklist = json.loads((r.root / "scan-worklist.json").read_text())
    task = next(t for t in worklist["tasks"] if t["id"] == "discover-areas")
    assert task["writeTo"] == ".sre/area-proposals.json"
    assert "discover-areas --target" in task["ingest"]


def test_confirmed_area_graduates_toward_a_collector_sketch(tmp_path):
    """The flywheel's last mile: confirmed areas accrue in the existing tracker, and the
    graduation sketch for an area-* category drafts a COLLECTOR, not a regex."""
    from sre_kb.graduation import ConfirmedCategory, GraduationTracker, draft_signature

    t = GraduationTracker()
    for i in range(5):
        t.confirm("area-db-migrations", anchor=f"db/migration/V{i}__x.sql:2")
    t.save(tmp_path)
    [cand] = GraduationTracker.load(tmp_path).candidates(5)
    assert cand.category == "area-db-migrations"
    sketch = draft_signature(cand, (), known=False)
    assert "COVERAGE AREA" in sketch and "NEW" in sketch and "COLLECTOR" in sketch
    assert "registry row" in sketch
    assert isinstance(ConfirmedCategory("area-x"), ConfirmedCategory)
