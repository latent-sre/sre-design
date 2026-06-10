"""Delivery-pipeline collector: .github/workflows/*.yml -> pipeline.workflow facts.

The app team's checked-in CI definition is deployment evidence the same way the PCF manifest
is: jobs are the pipeline's stages, push-trigger branches say what promotes, and a `cf push`
in a step marks the workflow as the one that deploys. Only what the file states is emitted —
promotion/rollback policy is not guessed.
"""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors.base import ScanContext, load_yaml_mapping
from sre_kb.models.facts import Fact, Symbol

_WORKFLOWS = ".github/workflows/"


def _branches(data: dict) -> list[str]:
    # YAML 1.1 parses a bare `on:` key as boolean True — accept both spellings.
    trigger = data.get("on", data.get(True)) or {}
    if not isinstance(trigger, dict):
        return []
    push = trigger.get("push")
    if not isinstance(push, dict):
        return []
    branches = push.get("branches")
    return [str(b) for b in branches] if isinstance(branches, list) else []


def _deploys_with_cf(jobs: dict) -> bool:
    # Both step styles count: a literal `cf push` in a run: script, or a marketplace
    # cloudfoundry action in uses: (e.g. cloudfoundry-community/*). A bespoke action that
    # hides cf entirely is still invisible — only what the file states is asserted.
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            if "cf push" in str(step.get("run", "")):
                return True
            if "cloudfoundry" in str(step.get("uses", "")).lower():
                return True
    return False


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.yml", "*.yaml"):
        rel = ctx.rel(path)
        if not rel.startswith(_WORKFLOWS):
            continue
        data, err = load_yaml_mapping(ctx, rel, "common.delivery_pipeline")
        if err is not None:
            facts.append(err)
        if data is None:
            continue
        jobs = data.get("jobs")
        if not isinstance(jobs, dict) or not jobs:
            continue
        name = str(data.get("name") or Path(rel).stem)
        branches = _branches(data)
        attrs = {
            "name": name,
            "system": "github-actions",
            "stages": [str(j) for j in jobs],
        }
        if branches:
            attrs["branch"] = branches[0]
        if _deploys_with_cf(jobs):
            attrs["deploysWith"] = "cf-push"
        facts.append(Fact(
            "pipeline.workflow",
            attrs,
            ctx.evidence(rel, 1, len(ctx.read_lines(rel)), "common.delivery_pipeline"),
            Symbol(name, "workflow"),
        ))
    return facts
