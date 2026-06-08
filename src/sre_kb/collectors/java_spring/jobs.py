"""Scheduled-job collector (AST-backed): Spring `@Scheduled` methods -> `job.scheduled` facts.

Tier-A deterministic coverage for recurring jobs. Pairs with the gap-finder's `undocumented-job`
probe (Tier-B recall): once a job is collected here it is *covered*, so the probe stops flagging it
— the §7.9 graduation dynamic. Detects `@Scheduled` directly from the code model (not via the shared
signature) so this collector is self-contained.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import fqn

_RATE_KEYS = ("fixedRate", "fixedDelay", "fixedRateString", "fixedDelayString")


def _schedule(args: dict) -> tuple[str, str]:
    """(jobType, human schedule) from `@Scheduled` args: a cron expr -> cron, else a fixed rate."""
    if "cron" in args:
        return "cron", args["cron"]
    for k in _RATE_KEYS:
        if k in args:
            return "scheduled", f"{k}={args[k]}"
    return "scheduled", args.get("", "")


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        module = ctx.module(rel, "java")
        ns = module.namespace
        for t in module.types:
            for m in t.methods:
                if "@Scheduled" not in m.annotations:
                    continue
                job_type, schedule = _schedule(m.annotations["@Scheduled"])
                handler = fqn(ns, t.name, m.name)
                attrs = {"name": f"{t.name}.{m.name}", "jobType": job_type, "trigger": handler}
                if schedule:
                    attrs["schedule"] = schedule
                if "@DisallowConcurrentExecution" in m.annotations:
                    attrs["concurrency"] = "forbid"
                facts.append(
                    Fact(
                        "job.scheduled",
                        attrs,
                        ctx.evidence(rel, m.start, m.name_line, "java_spring.jobs"),
                        Symbol(handler, "method"),
                    )
                )
    return facts
