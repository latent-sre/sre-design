"""Ingest an SLO catalog (sre-slo.yml) so objectives carry real targets/windows.

This is the 'ingested SLO catalog' source: when present, SloSli becomes a full objective
and the flow gets an error-budget burn-rate Alert instead of a needs-review threshold.
"""

from __future__ import annotations

import yaml

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact
from sre_kb.util import find_line


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("sre-slo.yml", "sre-slo.yaml"):
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = yaml.safe_load(ctx.read_text(rel)) or {}
        except yaml.YAMLError:
            continue
        for s in data.get("slos") or []:
            if not isinstance(s, dict):
                continue
            flow = s.get("flow")
            ln = (find_line(lines, str(flow)) if flow else 1) or 1
            facts.append(
                Fact(
                    "slo.objective",
                    {
                        "flow": flow,
                        "sli": s.get("sli", "latency"),
                        "target": s.get("target"),
                        "window": s.get("window"),
                        "percentile": s.get("objectivePercentile"),
                        "thresholdMs": s.get("thresholdMs"),
                    },
                    ctx.evidence(rel, ln, ln, "common.slo_catalog"),
                )
            )
    return facts
