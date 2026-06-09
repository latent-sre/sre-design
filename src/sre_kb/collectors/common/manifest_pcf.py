"""PCF manifest collector: manifest*.yml -> pcf.app / pcf.service-binding facts."""

from __future__ import annotations

import yaml

from sre_kb.collectors.base import ScanContext, parse_error_fact
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("manifest*.yml"):
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = yaml.safe_load(ctx.read_text(rel)) or {}
        except yaml.YAMLError as exc:
            facts.append(parse_error_fact(ctx, rel, "common.manifest_pcf", exc))
            continue
        if not isinstance(data, dict):
            continue  # a non-mapping root (list/scalar) is not a PCF manifest
        for app in data.get("applications") or []:
            if not isinstance(app, dict):
                continue
            name = app.get("name", "app")
            routes = [r.get("route") for r in (app.get("routes") or []) if isinstance(r, dict)]
            services = [s for s in (app.get("services") or []) if isinstance(s, str)]
            facts.append(
                Fact(
                    "pcf.app",
                    {
                        "name": name,
                        "instances": app.get("instances"),
                        "memory": app.get("memory"),
                        "disk": app.get("disk_quota"),
                        "stack": app.get("stack"),
                        "buildpacks": app.get("buildpacks") or [],
                        "routes": routes,
                        "services": services,
                        "env": app.get("env") or {},
                        "command": app.get("command"),
                        "healthCheck": {
                            "type": app.get("health-check-type"),
                            "endpoint": app.get("health-check-http-endpoint"),
                        },
                    },
                    ctx.evidence(rel, 1, len(lines), "common.manifest_pcf"),
                    Symbol(name, "pcf-app"),
                )
            )
            for svc in services:
                ln = find_line(lines, svc) or 1
                facts.append(
                    Fact(
                        "pcf.service-binding",
                        {"name": svc, "app": name},
                        ctx.evidence(rel, ln, ln, "common.manifest_pcf"),
                        Symbol(svc, "pcf-service"),
                    )
                )
    return facts
