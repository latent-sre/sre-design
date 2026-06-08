"""Graduation loop (HYBRID-PLAN §9.3 #3): recurring human-confirmed gap categories are tracked toward
a deterministic signature, and promoted only by an assisted human-merged draft (never auto-applied)."""

from __future__ import annotations

from typer.testing import CliRunner

from sre_kb.cli import app
from sre_kb.collectors.llm.gap_finder import gap_categories, target_concerns
from sre_kb.graduation import ConfirmedCategory, GraduationTracker, draft_signature

runner = CliRunner()


def test_confirm_increments_and_tracks_anchor():
    t = GraduationTracker()
    t.confirm("missing-timeout", run="r1", anchor="Foo.java:10")
    t.confirm("missing-timeout", run="r2", anchor="Bar.java:20")
    cat = t.categories["missing-timeout"]
    assert cat.confirmed == 2 and cat.false_positives == 0
    assert cat.last_run == "r2"
    assert cat.anchors == ["Foo.java:10", "Bar.java:20"]


def test_anchor_dedup_and_cap():
    t = GraduationTracker()
    for i in range(8):
        t.confirm("missing-timeout", anchor=f"a{i}")
    t.confirm("missing-timeout", anchor="a7")  # duplicate -> not re-added
    cat = t.categories["missing-timeout"]
    assert cat.confirmed == 9
    assert len(cat.anchors) == 5 and cat.anchors[-1] == "a7"  # capped to last 5


def test_refute_blocks_candidacy():
    t = GraduationTracker()
    for _ in range(5):
        t.confirm("missing-timeout")
    assert t.categories["missing-timeout"].is_candidate(5)
    t.refute("missing-timeout")
    assert not t.categories["missing-timeout"].is_candidate(5)  # any false positive blocks it


def test_is_candidate_threshold_and_promoted():
    c = ConfirmedCategory("missing-timeout", confirmed=4)
    assert not c.is_candidate(5)  # below threshold
    c.confirmed = 5
    assert c.is_candidate(5)  # meets threshold, no false positives
    c.promoted = True
    assert not c.is_candidate(5)  # already promoted -> no longer a candidate


def test_candidates_filters_and_orders():
    t = GraduationTracker()
    for _ in range(5):
        t.confirm("missing-timeout")
        t.confirm("undocumented-job")
    t.confirm("data-loss-path")  # below threshold
    assert [c.category for c in t.candidates(5)] == ["missing-timeout", "undocumented-job"]


def test_round_trip_yaml(tmp_path):
    t = GraduationTracker()
    t.confirm("missing-timeout", run="r1", anchor="x:1")
    t.refute("missing-timeout")
    t.save(tmp_path)
    assert (tmp_path / ".sre" / "graduation-tracker.yaml").is_file()
    cat = GraduationTracker.load(tmp_path).categories["missing-timeout"]
    assert cat.confirmed == 1 and cat.false_positives == 1
    assert cat.anchors == ["x:1"] and cat.last_run == "r1"


def test_load_missing_is_empty(tmp_path):
    assert GraduationTracker.load(tmp_path).categories == {}


def test_gap_categories_and_target_concerns():
    cats = gap_categories()
    assert {
        "missing-timeout", "unguarded-critical-dependency", "swallowed-failure",
        "undocumented-job", "data-loss-path",
    } <= cats
    assert target_concerns("missing-timeout") == ("timeout",)
    assert target_concerns("undocumented-job") == ("scheduled",)
    assert target_concerns("swallowed-failure") == ()  # AST detector, not a regex signature
    assert target_concerns("data-loss-path") == ()  # judgment call, no deterministic rule


def test_draft_signature_variants():
    d = draft_signature(
        ConfirmedCategory("missing-timeout", confirmed=5, anchors=["Foo.java:10"]),
        target_concerns("missing-timeout"),
    )
    assert "signatures.py concern(s): timeout" in d and "Foo.java:10" in d
    assert "AST swallow detector" in draft_signature(ConfirmedCategory("swallowed-failure", confirmed=5), ())
    assert "judgment-call" in draft_signature(ConfirmedCategory("data-loss-path", confirmed=5), ())


# --- CLI ------------------------------------------------------------------------------------------
def test_cli_confirm_gap_records(tmp_path):
    r = runner.invoke(app, ["confirm-gap", "missing-timeout", "--target", str(tmp_path),
                            "--anchor", "Foo.java:10", "--run", "demo"])
    assert r.exit_code == 0, r.stdout
    assert "1 confirmation(s)" in r.stdout
    cat = GraduationTracker.load(tmp_path).categories["missing-timeout"]
    assert cat.confirmed == 1 and cat.anchors == ["Foo.java:10"]


def test_cli_confirm_gap_rejects_unknown_category(tmp_path):
    r = runner.invoke(app, ["confirm-gap", "not-a-real-category", "--target", str(tmp_path)])
    assert r.exit_code == 2  # rejected before any state is written
    assert not (tmp_path / ".sre" / "graduation-tracker.yaml").exists()


def test_cli_false_positive(tmp_path):
    r = runner.invoke(app, ["confirm-gap", "missing-timeout", "--target", str(tmp_path), "--false-positive"])
    assert r.exit_code == 0
    assert GraduationTracker.load(tmp_path).categories["missing-timeout"].false_positives == 1


def test_cli_graduation_candidates_drafts_ready_category(tmp_path):
    t = GraduationTracker()
    for i in range(5):
        t.confirm("missing-timeout", anchor=f"Foo.java:{i}")
    t.confirm("undocumented-job")  # below threshold
    t.save(tmp_path)
    r = runner.invoke(app, ["graduation-candidates", "--target", str(tmp_path)])
    assert r.exit_code == 0, r.stdout
    assert "missing-timeout: READY to graduate" in r.stdout
    assert "signatures.py concern(s): timeout" in r.stdout  # the assisted draft
    assert "undocumented-job: 1/5" in r.stdout  # not yet ready
    assert "1 category ready to graduate" in r.stdout


def test_cli_graduation_candidates_empty(tmp_path):
    r = runner.invoke(app, ["graduation-candidates", "--target", str(tmp_path)])
    assert r.exit_code == 0
    assert "no gap confirmations recorded yet" in r.stdout


def test_save_is_atomic_and_preserves_prior_on_failure(tmp_path, monkeypatch):
    """#M7: a crash mid-save must not truncate the tracker (load treats a corrupt file as empty,
    silently discarding the tally). The prior file stays intact and no temp file leaks."""
    import sre_kb.graduation.state as st

    t = GraduationTracker()
    t.confirm("missing-timeout")
    t.save(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("disk full mid-write")

    monkeypatch.setattr(st.yaml, "safe_dump", boom)
    t.confirm("missing-timeout")  # in-memory now 2
    try:
        t.save(tmp_path)
    except RuntimeError:
        pass

    reloaded = GraduationTracker.load(tmp_path)
    assert reloaded.categories["missing-timeout"].confirmed == 1  # prior tally intact, not lost
    assert not list((tmp_path / ".sre").glob(".graduation-*.tmp"))  # no temp leak
