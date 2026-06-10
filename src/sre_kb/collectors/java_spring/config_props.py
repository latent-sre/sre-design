"""Spring config collector: application*.yml -> config.* facts (SLO, client timeouts,
time-limiter, actuator exposure). Each fact cites the defining line."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext, load_yaml_mapping
from sre_kb.models.facts import Fact
from sre_kb.util import dig, find_line


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("application.yml", "application.yaml", "application-*.yml"):
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        data, err = load_yaml_mapping(ctx, rel, "java_spring.config_props")
        if err is not None:
            facts.append(err)
        if data is None:
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

        # External config sources: `spring.config.import` entries (configserver:/vault:/file:,
        # optionally `optional:`-prefixed) and the legacy `spring.cloud.config.uri`. These declare
        # where config actually comes from at runtime — a sources list built only from the files
        # the other facts cite can't see them.
        imp = dig(data, "spring", "config", "import")
        for entry in imp if isinstance(imp, list) else [imp] if isinstance(imp, str) else []:
            if not isinstance(entry, str) or ":" not in entry:
                continue
            optional = entry.startswith("optional:")
            kind, _, uri = entry.removeprefix("optional:").partition(":")
            ln = find_line(lines, entry) or find_line(lines, "import") or 1
            facts.append(
                Fact(
                    "config.source",
                    {"kind": kind, "uri": uri, "optional": optional},
                    ctx.evidence(rel, ln, ln, "java_spring.config_props"),
                )
            )
        legacy_uri = dig(data, "spring", "cloud", "config", "uri")
        if isinstance(legacy_uri, str):
            ln = find_line(lines, legacy_uri) or find_line(lines, "uri") or 1
            facts.append(
                Fact(
                    "config.source",
                    {"kind": "configserver", "uri": legacy_uri, "optional": False},
                    ctx.evidence(rel, ln, ln, "java_spring.config_props"),
                )
            )
    return facts
