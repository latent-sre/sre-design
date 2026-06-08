"""KB persistence lifecycle (#H3, #M1): a re-run under the same run-id must not leak stale
artifacts, and a rejected artifact must never also land in the live KB tree."""

from __future__ import annotations

from pathlib import Path

from sre_kb.pipeline import run as run_pipeline
from sre_kb.pipeline.orchestrator import _dest_dir
from sre_kb.workspace import RunLayout

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def test_rerun_under_same_run_id_clears_stale_artifacts(tmp_path):
    """#H3: `diff` reuses fixed run-ids and a re-`run` writes by name only. A stale artifact from a
    prior run under the same id must be cleared, not silently re-read by load_kb."""
    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="r", to_stage="validate")
    layout = RunLayout(Path(str(tmp_path)), "r")
    stale = layout.kb / "verified" / "Flow" / "ghost-flow.yaml"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("kind: Flow\nmetadata:\n  name: ghost-flow\n", encoding="utf-8")

    run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="r", to_stage="validate")
    assert not stale.exists(), "stale artifact from a prior same-id run leaked into the result"


def test_dest_dir_keeps_rejected_out_of_kb(tmp_path):
    """#M1: a rejected artifact (incl. a recomputed ReadinessScore) routes to reports/rejected,
    never into kb/needs-review — so load_kb can't surface a rejected artifact as live."""
    layout = RunLayout(Path(str(tmp_path)), "r")
    assert _dest_dir(layout, "rejected", "ReadinessScore") == layout.reports / "rejected" / "ReadinessScore"
    assert _dest_dir(layout, "needs-review", "ReadinessScore") == layout.kb / "needs-review" / "ReadinessScore"
    assert _dest_dir(layout, "verified", "Flow") == layout.kb / "verified" / "Flow"
