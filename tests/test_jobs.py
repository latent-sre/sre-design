"""ScheduledJob kind + @Scheduled collector (HYBRID-PLAN §9.6, adopted from resiliency-skills).

Tier-A coverage for recurring jobs: the engine detects @Scheduled methods deterministically and
emits a byte-grounded, verified ScheduledJob per job. (Pairs with the gap-finder's Tier-B
undocumented-job probe, which covers jobs no collector reaches.)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.validation import validate_kb_tree

FIXTURE = Path(__file__).parent / "fixtures" / "sample-jobs"


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp("jobwork")
    return run_pipeline(str(FIXTURE), work_root=str(work), run_id="j", to_stage="validate")


def _jobs(root: Path) -> dict[str, dict]:
    out = {}
    for p in (root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        if d["kind"] == "ScheduledJob":
            out[d["metadata"]["name"]] = d
    return out


def test_both_scheduled_jobs_detected(result):
    jobs = _jobs(result.root)
    assert len(jobs) == 2
    specs = {d["spec"]["name"]: d["spec"] for d in jobs.values()}
    # a cron job -> jobType cron + the cron expression
    cron = specs["InvoiceJobs.nightlyInvoiceRun"]
    assert cron["jobType"] == "cron" and cron["schedule"] == "0 0 2 * * *"
    # a fixed-rate job -> jobType scheduled + the rate
    poll = specs["InvoiceJobs.pollPaymentStatus"]
    assert poll["jobType"] == "scheduled" and poll["schedule"] == "fixedRate=60000"


def test_positional_scheduled_value_is_cron_only_when_cron_shaped():
    """A bare positional @Scheduled("...") is meaningful only as a cron expr; anything else carries
    no usable schedule rather than being mislabelled as a fixed rate."""
    from sre_kb.collectors.java_spring.jobs import _schedule

    assert _schedule({"": "0 0 2 * * *"}) == ("cron", "0 0 2 * * *")  # cron-shaped -> cron
    assert _schedule({"": "everyNight"}) == ("scheduled", "")          # not cron -> no schedule
    assert _schedule({"": ""}) == ("scheduled", "")                    # empty -> no schedule
    # named attributes still win
    assert _schedule({"cron": "* * * * * *"}) == ("cron", "* * * * * *")
    assert _schedule({"fixedRate": "60000"}) == ("scheduled", "fixedRate=60000")


def test_scheduled_jobs_are_tier_a_verified_and_grounded(result):
    jobs = _jobs(result.root)
    cron = jobs["invoice-jobs-nightly-invoice-run"]
    assert cron["status"] == "verified"                 # deterministic detection -> Tier-A
    assert cron["evidence"][0]["source_tier"] == "ast"
    assert cron["evidence"][0]["path"].endswith("InvoiceJobs.java")
    # the whole KB validates structurally + provenance
    assert not [r for r in validate_kb_tree(result.root / "kb") if not r.ok]
