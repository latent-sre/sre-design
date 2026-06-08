"""Spring config collector: application*.yml -> config.* facts (SLO, client timeouts,
time-limiter, actuator exposure). Each fact cites the defining line."""

from __future__ import annotations

import yaml

from sre_kb.collectors.base import ScanContext, parse_error_fact
from sre_kb.models.facts import Fact
from sre_kb.util import dig, find_line


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("application.yml", "application.yaml", "application-*.yml"):
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = yaml.safe_load(ctx.read_text(rel)) or {}
        except yaml.YAMLError as exc:
            facts.append(parse_error_fact(ctx, rel, "java_spring.config_props", exc))
            continue

        slo = dig(data, "management", "metrics", "distribution", "slo")
        if isinstance(slo, dict):
            for meter, buckets in slo.items():
                ln = find_line(lines, str(meter)) or 1
                facts.append(
                    Fact(
                        "config.slo",
                        {"meter": meter, "buckets": str(buckets)},
                        ctx.evidence(rel, ln, ln, "java_spring.config_props"),
                    )
                )

        clients = dig(data, "clients")
        if isinstance(clients, dict):
            for cname, cval in clients.items():
                if isinstance(cval, dict) and "timeout" in cval:
                    ln = find_line(lines, str(cname)) or 1
                    end = find_line(lines, "timeout", ln) or ln
                    facts.append(
                        Fact(
                            "config.client",
                            {
                                "client": cname,
                                "timeout": str(cval["timeout"]),
                                "baseUrl": cval.get("base-url"),
                            },
                            ctx.evidence(rel, ln, end, "java_spring.config_props"),
                        )
                    )

        tl = dig(data, "resilience4j", "timelimiter", "instances")
        if isinstance(tl, dict):
            for inst, val in tl.items():
                if isinstance(val, dict) and "timeoutDuration" in val:
                    # Anchor on this instance first, then find its timeoutDuration — otherwise every
                    # instance cites the first timeoutDuration in the file (mirrors the client path).
                    inst_ln = find_line(lines, str(inst)) or 1
                    ln = find_line(lines, "timeoutDuration", inst_ln) or inst_ln
                    facts.append(
                        Fact(
                            "config.timelimiter",
                            {"instance": inst, "timeout": str(val["timeoutDuration"])},
                            ctx.evidence(rel, ln, ln, "java_spring.config_props"),
                        )
                    )

        exposure = dig(data, "management", "endpoints", "web", "exposure", "include")
        if exposure:
            ln = find_line(lines, "include") or 1
            facts.append(
                Fact(
                    "config.actuator",
                    {"exposure": str(exposure)},
                    ctx.evidence(rel, ln, ln, "java_spring.config_props"),
                )
            )
    return facts
