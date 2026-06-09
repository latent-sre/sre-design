"""The unified scan worklist is the single front door for the manual LLM loop: it must enumerate
exactly the tasks that have work (no empty steps), point each to where to read context and where to
save output, and carry the pointer-generator contract."""

from __future__ import annotations

from sre_kb.synth.worklist import SCHEMA, build_scan_worklist


def test_includes_both_modes_when_both_have_work():
    wl = build_scan_worklist("r1", service="orders", target="/t", context_packs=3, challenge_items=2)
    assert wl["schema"] == SCHEMA
    assert wl["runId"] == "r1" and wl["service"] == "orders" and wl["target"] == "/t"
    modes = {t["mode"] for t in wl["tasks"]}
    assert modes == {"discover", "confirm"}
    assert "pointer-generator" in wl["contract"]


def test_discover_task_points_to_target_output():
    wl = build_scan_worklist("r1", service="s", target="/t", context_packs=1, challenge_items=0)
    assert [t["id"] for t in wl["tasks"]] == ["discover-gaps"]  # confirm omitted: no claims
    t = wl["tasks"][0]
    assert t["writeToBase"] == "target" and t["writeTo"] == ".sre/gap-proposals.json"
    assert "candidates/context/" in t["reads"]
    assert t["skill"].endswith("sre-gap-finder/SKILL.md")
    assert "sre-kb run --target /t" in t["ingest"]


def test_confirm_task_points_to_run_output_and_counts_claims():
    wl = build_scan_worklist("run9", service="s", target="/t", context_packs=0, challenge_items=5)
    assert [t["id"] for t in wl["tasks"]] == ["confirm-challenge"]  # discover omitted: no packs
    t = wl["tasks"][0]
    assert t["writeToBase"] == "run" and t["writeTo"] == "challenge/verdicts.json"
    assert "5 judgment-call claim" in t["title"]
    assert "challenge/worklist.json" in t["reads"]
    assert "sre-kb challenge-apply --run run9" in t["ingest"]


def test_empty_worklist_has_no_tasks_but_is_well_formed():
    wl = build_scan_worklist("r", service="s", target="/t", context_packs=0, challenge_items=0)
    assert wl["tasks"] == []
    assert wl["schema"] == SCHEMA  # still a valid, parseable manifest
