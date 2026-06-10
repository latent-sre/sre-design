"""Node.js `package.json` collector — emits the normalized tech-stack facts the unchanged scaffolder
turns into a `TechStack` (and feeds into the dependency roll-ups), same as the Java/.NET/Python
collectors. Direct JSON parse only; safe-by-default (no build executed, no AST, no new dependency).

Scope of this slice: web framework (express/koa/fastify/nest/...), runtime (node + build tool), and
the runtime dependency list. Only `dependencies` are emitted, not `devDependencies` — SRE posture is
about what runs in production, and build/test tooling is noise here. REST endpoint and egress
extraction need a JavaScript AST and are a follow-up.

Self-gating: a target with no `package.json` emits nothing.
"""

from __future__ import annotations

import json

from sre_kb.collectors.base import ScanContext, parse_error_fact
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

# Dependency name -> canonical framework label. Ordered most-specific first so a Nest app (which also
# depends on a platform adapter) resolves to nest, not the adapter. First match in this order wins.
_FRAMEWORKS: tuple[tuple[str, str], ...] = (
    ("@nestjs/core", "nestjs"),
    ("@hapi/hapi", "hapi"),
    ("fastify", "fastify"),
    ("koa", "koa"),
    ("express", "express"),
    ("restify", "restify"),
    ("hapi", "hapi"),
)


def _framework(deps: dict) -> tuple[str, str] | None:
    """The (dependency name, canonical label) of the web framework in a package's deps, or None.
    Returns the matched dependency so the caller can cite that exact line in package.json."""
    return next(((dep, label) for dep, label in _FRAMEWORKS if dep in deps), None)


def _build_tool(ctx: ScanContext) -> str:
    """The package manager, inferred from the lockfile present (npm is the default)."""
    if ctx.files("pnpm-lock.yaml"):
        return "pnpm"
    if ctx.files("yarn.lock"):
        return "yarn"
    return "npm"


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    pkgs = ctx.files("package.json")
    if not pkgs:
        return facts

    language = "typescript" if ctx.files("tsconfig.json") else "javascript"
    seen_deps: set[str] = set()
    runtime_done = False
    for path in pkgs:
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = json.loads(ctx.read_text(rel)) or {}
        except (json.JSONDecodeError, ValueError) as exc:
            facts.append(parse_error_fact(ctx, rel, "node_express.package_json", exc))
            continue
        if not isinstance(data, dict):
            continue
        deps = data.get("dependencies") or {}
        if not isinstance(deps, dict):
            deps = {}

        if not runtime_done:
            ln = find_line(lines, '"name"') or 1
            ev = ctx.evidence(rel, ln, ln, "node_express.package_json")
            facts.append(Fact(
                "tech.runtime",
                {"language": language, "runtime": "node", "buildTool": _build_tool(ctx)},
                ev, Symbol("node", "runtime"),
            ))
            fw = _framework(deps)
            if fw:
                dep_name, label = fw
                fln = find_line(lines, f'"{dep_name}"') or ln
                facts.append(Fact(
                    "tech.framework", {"name": label},
                    ctx.evidence(rel, fln, fln, "node_express.package_json"),
                    Symbol(label, "framework"),
                ))
            runtime_done = True

        for name in deps:
            if name in seen_deps:
                continue
            seen_deps.add(name)
            ln = find_line(lines, f'"{name}"') or 1
            attrs: dict = {"name": name}
            if isinstance(deps[name], str):
                attrs["version"] = deps[name]
            facts.append(Fact(
                "tech.dependency", attrs,
                ctx.evidence(rel, ln, ln, "node_express.package_json"),
                Symbol(name, "dependency"),
            ))
    return facts
