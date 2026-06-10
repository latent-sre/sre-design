"""PCF manifest collector: manifest*.yml (+ sibling vars files) -> pcf.app /
pcf.service-binding facts. `manifest-<env>.yml` variants resolve `((var))` interpolation
against `vars-<env>.yml` (falling back to `vars.yml`) and carry the environment name, so
the KB gains an environments dimension from files the repo already checks in."""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext, load_yaml_mapping
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_VAR = re.compile(r"\(\(\s*([\w.-]+)\s*\)\)")


def _env_of(rel: str) -> str | None:
    """The environment a manifest variant targets: manifest-prod.yml -> 'prod'; manifest.yml -> None."""
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    _, sep, env = stem.partition("-")
    return env if sep and env else None


def _vars_for(ctx: ScanContext, manifest_rel: str, env: str | None,
              detector: str) -> tuple[dict, Fact | None]:
    """The vars mapping a `cf push --vars-file` of this manifest would use: `vars-<env>.yml`
    beside an env variant, else `vars.yml`. Missing files are simply no vars."""
    base = manifest_rel.rsplit("/", 1)[0] + "/" if "/" in manifest_rel else ""
    candidates = ([f"{base}vars-{env}.yml"] if env else []) + [f"{base}vars.yml"]
    for rel in candidates:
        if not (ctx.root / rel).is_file():
            continue
        data, err = load_yaml_mapping(ctx, rel, detector)
        return data or {}, err
    return {}, None


def _interpolate(value: object, variables: dict) -> object:
    """Resolve `((var))` placeholders recursively. A scalar that is exactly one placeholder takes
    the variable's native type (`instances: ((web-instances))` stays an int); placeholders inside
    a longer string substitute textually. Unknown variables are left as-is (the manifest is still
    evidence of the shape, even when a vars file is incomplete)."""
    if isinstance(value, dict):
        return {k: _interpolate(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, variables) for v in value]
    if not isinstance(value, str):
        return value
    whole = _VAR.fullmatch(value.strip())
    if whole and whole.group(1) in variables:
        return variables[whole.group(1)]
    return _VAR.sub(lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0),
                    value)


def _service_entries(app: dict) -> list[tuple[str, dict | None]]:
    """`services:` entries as (name, binding-parameters): plain strings and the v3 map form
    (`- name: x` with optional `parameters:`) both bind; anything else is ignored."""
    out: list[tuple[str, dict | None]] = []
    for s in app.get("services") or []:
        if isinstance(s, str):
            out.append((s, None))
        elif isinstance(s, dict) and isinstance(s.get("name"), str):
            params = s.get("parameters")
            out.append((s["name"], params if isinstance(params, dict) else None))
    return out


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    all_rels = sorted(ctx.rel(p) for p in ctx.files("manifest*.yml"))
    # A `-<suffix>` manifest is an ENV variant only when a base manifest.yml sits beside it;
    # standalone manifest-api.yml / manifest-worker.yml is the per-app convention, not
    # environments named "api"/"worker".
    base_dirs = {rel.rsplit("/", 1)[0] if "/" in rel else ""
                 for rel in all_rels if rel.rsplit("/", 1)[-1] == "manifest.yml"}

    def env_for(rel: str) -> str | None:
        rel_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
        return _env_of(rel) if rel_dir in base_dirs else None

    # Base manifests first, env variants after: `fs.first("pcf.app")` (service identity, the
    # Deployment roll-up) must keep reading the unsuffixed manifest, not whichever variant
    # happens to sort first.
    rels = sorted(all_rels, key=lambda r: (env_for(r) is not None, r))
    for rel in rels:
        lines = ctx.read_lines(rel)
        data, err = load_yaml_mapping(ctx, rel, "common.manifest_pcf")
        if err is not None:
            facts.append(err)
        if data is None:
            continue
        env_name = env_for(rel)
        variables, vars_err = _vars_for(ctx, rel, env_name, "common.manifest_pcf")
        if vars_err is not None:
            facts.append(vars_err)
        data = _interpolate(data, variables)
        for app in data.get("applications") or []:
            if not isinstance(app, dict):
                continue
            name = app.get("name", "app")
            routes = [
                r["route"] for r in (app.get("routes") or [])
                if isinstance(r, dict) and r.get("route")
            ]
            bindings = _service_entries(app)
            processes = [
                {"type": p["type"], "instances": p.get("instances"), "memory": p.get("memory"),
                 "command": p.get("command"), "healthCheckType": p.get("health-check-type")}
                for p in (app.get("processes") or [])
                if isinstance(p, dict) and p.get("type")
            ]
            sidecars = [
                {"name": s["name"], "command": s.get("command"),
                 "processTypes": s.get("process_types") or []}
                for s in (app.get("sidecars") or [])
                if isinstance(s, dict) and s.get("name")
            ]
            attrs = {
                "name": name,
                "instances": app.get("instances"),
                "memory": app.get("memory"),
                "disk": app.get("disk_quota"),
                "stack": app.get("stack"),
                "buildpacks": app.get("buildpacks") or [],
                "routes": routes,
                "services": [n for n, _ in bindings],
                "env": app.get("env") or {},
                "command": app.get("command"),
                "healthCheck": {
                    "type": app.get("health-check-type"),
                    "endpoint": app.get("health-check-http-endpoint"),
                },
                "processes": processes,
                "sidecars": sidecars,
            }
            if env_name:
                attrs["environment"] = env_name
            if app.get("no-route"):
                attrs["noRoute"] = True
            if app.get("random-route"):
                attrs["randomRoute"] = True
            facts.append(
                Fact(
                    "pcf.app",
                    attrs,
                    ctx.evidence(rel, 1, len(lines), "common.manifest_pcf"),
                    Symbol(name, "pcf-app"),
                )
            )
            for svc, params in bindings:
                ln = find_line(lines, svc) or 1
                battrs: dict = {"name": svc, "app": name}
                if params:
                    battrs["parameters"] = params
                facts.append(
                    Fact(
                        "pcf.service-binding",
                        battrs,
                        ctx.evidence(rel, ln, ln, "common.manifest_pcf"),
                        Symbol(svc, "pcf-service"),
                    )
                )
    return facts
