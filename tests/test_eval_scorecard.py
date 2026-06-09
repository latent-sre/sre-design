"""S5 eval harness: the rubric-as-spec scorecard over a labeled fixture."""

from __future__ import annotations

from pathlib import Path

from sre_kb.eval.scorecard import EvalTruth, Scorecard, load_eval_truth, score_target

FIXTURES = Path(__file__).parent / "fixtures"
SPRING = FIXTURES / "sample-spring-pcf"
TRUTH = SPRING / ".sre" / "eval-truth.json"


def test_labeled_fixture_scores_clean(tmp_path):
    sc = score_target(SPRING, load_eval_truth(TRUTH), work_root=str(tmp_path), run_id="ev")
    overall = sc.overall()
    # the labeled areas all extract correctly -> perfect recall + (scoped) precision
    assert overall["recall"] == 1.0
    assert overall["precision"] == 1.0
    assert overall["detectorRecall"] == 1.0
    # the new S2/S3/S4 detectors are exercised by the rubric
    assert "java_spring.log_statements" in sc.fired_detectors


def test_per_area_reports_each_labeled_kind(tmp_path):
    sc = score_target(SPRING, load_eval_truth(TRUTH), work_root=str(tmp_path), run_id="ev")
    area = sc.per_area()
    assert area["Flow"]["recall"] == 1.0 and area["Flow"]["verified"] == 1
    assert area["Dependency"]["matched"] == 3
    # an unlabeled kind (Architecture) is out of scope — not scored, not a precision hit
    assert "Architecture" not in area
    assert overall_precision_unhurt_by_unlabeled_kinds(sc)


def overall_precision_unhurt_by_unlabeled_kinds(sc: Scorecard) -> bool:
    # the run produces many kinds the truth doesn't label; precision stays 1.0 regardless
    return sc.overall()["precision"] == 1.0 and sc.overall()["artifactCount"] > sc.overall()["inScopeProduced"]


def test_missing_artifact_is_a_recall_miss():
    # a truth that expects an artifact the engine didn't produce -> recall < 1, surfaced in `missed`
    truth = EvalTruth(service="s", artifacts={("Flow", "create-order"), ("Flow", "ghost-flow")},
                      detectors=set())
    sc = Scorecard("t", truth.artifacts, {("Flow", "create-order")},
                   {("Flow", "create-order"): "verified"}, set(), set())
    assert sc.overall()["recall"] == 0.5
    assert sc.per_area()["Flow"]["missed"] == ["ghost-flow"]


def test_unexpected_artifact_in_labeled_kind_is_a_precision_miss():
    truth_arts = {("Flow", "create-order")}
    produced = {("Flow", "create-order"), ("Flow", "surprise-flow")}
    sc = Scorecard("t", truth_arts, produced,
                   {k: "verified" for k in produced}, set(), set())
    assert sc.overall()["precision"] == 0.5             # an extra Flow is a false positive
    assert sc.per_area()["Flow"]["unexpected"] == ["surprise-flow"]


def test_detector_coverage_flags_a_missing_detector():
    sc = Scorecard("t", set(), set(), {}, {"a.b", "c.d"}, {"a.b"})
    cov = sc.detector_coverage()
    assert cov["recall"] == 0.5 and cov["missing"] == ["c.d"]


def test_messaging_fixture_scores_clean(tmp_path):
    """The harness generalizes across sample-* repos: S3's Messaging extraction also scores 1.0."""
    target = FIXTURES / "sample-messaging"
    sc = score_target(target, load_eval_truth(target / ".sre" / "eval-truth.json"),
                      work_root=str(tmp_path), run_id="evm")
    assert sc.overall()["recall"] == 1.0 and sc.overall()["precision"] == 1.0
    assert sc.per_area()["ResiliencyGap"]["matched"] == 2     # consumer-without-dlq + non-idempotent
    assert sc.per_area()["Messaging"]["verified"] == 1
