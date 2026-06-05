"""Drift detection: identical scans diff to empty; fixing the swallowed publish removes
the Alert/Runbook and clears the data-loss risk — surfaced as drift."""

from __future__ import annotations

import shutil
from pathlib import Path

from sre_kb.drift import diff_kb
from sre_kb.pipeline import run as run_pipeline
from sre_kb.render import load_kb

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"
PUBLISHER = "src/main/java/com/acme/order/events/OrderEventPublisher.java"


def _kb(target: Path, work: Path, run_id: str) -> list[dict]:
    return load_kb(run_pipeline(str(target), work_root=str(work), run_id=run_id, to_stage="validate").root)


def test_identical_scans_have_no_drift(tmp_path):
    work = tmp_path / "w"
    base = _kb(FIXTURE, work, "i1")
    head = _kb(FIXTURE, work, "i2")
    assert diff_kb(base, head).is_empty()


def test_fixing_swallow_shows_drift(tmp_path):
    base_dir, head_dir = tmp_path / "base", tmp_path / "head"
    shutil.copytree(FIXTURE, base_dir)
    shutil.copytree(FIXTURE, head_dir)
    pub = head_dir / PUBLISHER
    fixed = pub.read_text().replace(
        'log.error("failed to publish order.created event for order {}", event.getOrderId(), e);',
        'throw new RuntimeException("publish failed", e);',
    )
    pub.write_text(fixed)

    work = tmp_path / "w"
    d = diff_kb(_kb(base_dir, work, "b"), _kb(head_dir, work, "h"))

    removed_kinds = {k[0] for k in d.removed}
    assert "Alert" in removed_kinds
    assert "Runbook" in removed_kinds
    # the order-created blast radius changes (data-loss cleared)
    assert ("BlastRadius", "order-created") in d.changed
