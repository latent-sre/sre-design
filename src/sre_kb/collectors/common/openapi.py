"""API-contract ingest (coverage matrix #7) — Tier-A.

The engine detects REST endpoints from code; this ingests an *existing* OpenAPI/AsyncAPI document if
the repo ships one (never generated — SCOPE §7) so the `Interface` kind can flag **contract drift**:
endpoints the code exposes but the spec doesn't document (undocumented), and paths the spec documents
that no handler serves (spec-only / dead doc). Byte-grounded: each spec operation cites its line.

Emits `api.spec.endpoint` / `api.spec.channel` facts; `synth/inventory.py` joins them to the detected
endpoints in the `Interface` artifact. Versioning / breaking-change judgment (needs a baseline to diff)
stays a Tier-B follow-up.
"""

from __future__ import annotations

import yaml

from sre_kb.collectors.base import ScanContext, parse_error_fact
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_SPEC_GLOBS = ("openapi.yaml", "openapi.yml", "openapi.json",
               "swagger.yaml", "swagger.yml", "swagger.json",
               "asyncapi.yaml", "asyncapi.yml", "asyncapi.json")
_HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}


def normalize_path(path: str) -> str:
    """A path key for matching a spec path against a detected route, template-insensitive:
    `/orders/{id}` and `/orders/{orderId}` both become `/orders/{}` (trailing slash stripped)."""
    out, depth = [], 0
    for ch in path:
        if ch == "{":
            depth += 1
            if depth == 1:
                out.append("{}")
        elif ch == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    norm = "".join(out).rstrip("/")
    return norm or "/"


def _spec_kind(data: dict) -> str | None:
    if "openapi" in data or "swagger" in data:
        return "openapi"
    if "asyncapi" in data:
        return "asyncapi"
    return None


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files(*_SPEC_GLOBS):
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = yaml.safe_load(ctx.read_text(rel)) or {}
        except yaml.YAMLError as exc:
            facts.append(parse_error_fact(ctx, rel, "common.openapi", exc))
            continue
        if not isinstance(data, dict):
            continue
        kind = _spec_kind(data)
        if kind is None:
            continue
        version = str((data.get("info") or {}).get("version") or "")

        if kind == "openapi":
            paths = data.get("paths")
            if not isinstance(paths, dict):
                continue
            for route, ops in paths.items():
                if not isinstance(ops, dict):
                    continue
                ln = find_line(lines, f"{route}:") or 1
                for method, op in ops.items():
                    if method.lower() not in _HTTP_METHODS:
                        continue
                    op_id = (op or {}).get("operationId") if isinstance(op, dict) else None
                    facts.append(Fact(
                        "api.spec.endpoint",
                        {"method": method.upper(), "path": str(route),
                         "normPath": normalize_path(str(route)), "operationId": op_id,
                         "specPath": rel, "specVersion": version, "source": "openapi"},
                        ctx.evidence(rel, ln, ln, "common.openapi"),
                        Symbol(f"{method.upper()} {route}", "operation"),
                    ))
        else:  # asyncapi
            channels = data.get("channels")
            if not isinstance(channels, dict):
                continue
            for channel in channels:
                ln = find_line(lines, f"{channel}:") or 1
                facts.append(Fact(
                    "api.spec.channel",
                    {"channel": str(channel), "specPath": rel, "specVersion": version,
                     "source": "asyncapi"},
                    ctx.evidence(rel, ln, ln, "common.openapi"),
                    Symbol(str(channel), "channel"),
                ))
    return facts
