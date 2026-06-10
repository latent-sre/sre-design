"""API-contract ingest + baseline diff (coverage matrix #7) — Tier-A.

The engine detects REST endpoints from code; this ingests an *existing* OpenAPI/AsyncAPI document if
the repo ships one (never generated — SCOPE §7) so the `Interface` kind can flag **contract drift**:
endpoints the code exposes but the spec doesn't document (undocumented), and paths the spec documents
that no handler serves (spec-only / dead doc). Byte-grounded: each spec operation cites its line.

If the repo also commits a **baseline** spec under `.sre/api-baseline/` (the last released contract),
this diffs the current spec against it and emits the *provable* breaking/non-breaking changes — an
operation removed (breaking), an operation added (non-breaking), a newly-required request parameter
(breaking) — plus a deterministic semver **version-policy** check (a breaking change with no major
bump). These are Tier-A: provable from the two documents, byte-grounded to the spec line, and can
verify. The *judgment* half — semantic breaks the shape diff can't see (units/default/enum meaning),
and whether a structural change actually breaks a given consumer — stays the Tier-B `map-api-contracts`
skill, which re-grounds against exactly these facts.
"""

from __future__ import annotations


from sre_kb.collectors.base import ScanContext, load_yaml_mapping
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_SPEC_GLOBS = ("openapi.yaml", "openapi.yml", "openapi.json",
               "swagger.yaml", "swagger.yml", "swagger.json",
               "asyncapi.yaml", "asyncapi.yml", "asyncapi.json")
_HTTP_METHODS = {"get", "put", "post", "delete", "patch", "head", "options", "trace"}

# A repo commits its last-released contract here so the engine can diff the current spec against it.
# Same-named file wins (openapi.yaml ↔ .sre/api-baseline/openapi.yaml); these files are *only* the
# diff baseline — they never feed the current-spec ingest (they'd otherwise double-count endpoints).
BASELINE_DIR = ".sre/api-baseline"


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


def _spec_version(data: dict) -> str:
    return str((data.get("info") or {}).get("version") or "")


def _required_params(path_item: dict, op: dict) -> set[str]:
    """The required request inputs of an operation, as stable `in:name` tokens (plus `(requestBody)`
    when a required body is declared). Path-level parameters merge into each operation, mirroring the
    OpenAPI spec. Only `required: true` parameters count — an optional parameter is non-breaking."""
    names: set[str] = set()
    for params in (path_item.get("parameters"), op.get("parameters")):
        for p in params or []:
            if isinstance(p, dict) and p.get("required") is True and p.get("name"):
                names.add(f"{p.get('in', 'query')}:{p['name']}")
    body = op.get("requestBody")
    if isinstance(body, dict) and body.get("required") is True:
        names.add("(requestBody)")
    return names


def _operations(data: dict) -> dict[tuple[str, str], dict]:
    """Map every OpenAPI operation to `(METHOD, normPath) -> {path, requiredParams}`, the comparable
    shape the baseline diff keys off."""
    ops: dict[tuple[str, str], dict] = {}
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return ops
    for route, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            key = (method.upper(), normalize_path(str(route)))
            ops[key] = {"path": str(route), "requiredParams": _required_params(path_item, op)}
    return ops


def _major(version: str) -> int | None:
    """The leading integer of a semver-ish version string (`1.2.0` -> 1), or None if unparseable."""
    head = version.strip().lstrip("vV").split(".", 1)[0]
    return int(head) if head.isdigit() else None


def _ref(method: str, norm_path: str) -> str:
    return f"{method} {norm_path}"


def _baseline_specs(ctx: ScanContext) -> dict[str, tuple[str, dict]]:
    """Parse every baseline spec under `.sre/api-baseline/`, keyed by file *name* so a current spec
    matches its same-named baseline. Returns `name -> (relpath, parsed_data)`; unparseable or
    non-OpenAPI baselines are skipped (the baseline is advisory — a broken one must not abort the scan)."""
    out: dict[str, tuple[str, dict]] = {}
    prefix = BASELINE_DIR + "/"
    for path in ctx.files(*_SPEC_GLOBS):
        rel = ctx.rel(path)
        if not rel.startswith(prefix):
            continue
        data, _ = load_yaml_mapping(ctx, rel, "common.openapi")  # baseline is advisory: no error fact
        if data is not None and _spec_kind(data) == "openapi":
            out[path.name] = (rel, data)
    return out


def _diff_facts(ctx: ScanContext, cur_rel: str, cur_data: dict,
                base_rel: str, base_data: dict) -> list[Fact]:
    """Deterministic breaking-change diff of `cur` vs its `base` baseline. Each change is byte-grounded
    to the spec line that proves it (the baseline file for a removed op, the current file otherwise)."""
    cur_ops, base_ops = _operations(cur_data), _operations(base_data)
    cur_lines, base_lines = ctx.read_lines(cur_rel), ctx.read_lines(base_rel)
    cur_ver, base_ver = _spec_version(cur_data), _spec_version(base_data)
    common = {"specPath": cur_rel, "baselinePath": base_rel,
              "specVersion": cur_ver, "baselineVersion": base_ver}

    def change(change_type: str, key: tuple[str, str], breaking: bool, rel: str,
               lines: list[str], route: str, detail: str | None) -> Fact:
        ln = find_line(lines, f"{route}:") or 1
        attrs = {"changeType": change_type, "ref": _ref(*key), "breaking": breaking,
                 "detail": detail, **common}
        return Fact("api.contract.change", attrs,
                    ctx.evidence(rel, ln, ln, "common.openapi"),
                    Symbol(f"{change_type} {_ref(*key)}", "contract-change"))

    facts: list[Fact] = []
    for key in sorted(base_ops.keys() - cur_ops.keys()):  # removed -> breaking
        facts.append(change("operation-removed", key, True, base_rel, base_lines,
                            base_ops[key]["path"], "operation removed from the contract"))
    for key in sorted(cur_ops.keys() - base_ops.keys()):  # added -> non-breaking
        facts.append(change("operation-added", key, False, cur_rel, cur_lines,
                            cur_ops[key]["path"], "operation added to the contract"))
    for key in sorted(cur_ops.keys() & base_ops.keys()):  # newly-required params -> breaking
        new_required = sorted(cur_ops[key]["requiredParams"] - base_ops[key]["requiredParams"])
        if new_required:
            facts.append(change("required-parameter-added", key, True, cur_rel, cur_lines,
                                cur_ops[key]["path"],
                                f"newly-required request input(s): {', '.join(new_required)}"))

    breaking_count = sum(1 for f in facts if f.attrs["breaking"])
    cur_major, base_major = _major(cur_ver), _major(base_ver)
    major_bumped = (cur_major is not None and base_major is not None and cur_major > base_major)
    # A version-policy violation only when the bump is *provably* insufficient (both versions parse).
    ok = breaking_count == 0 or major_bumped or cur_major is None or base_major is None
    ln = find_line(cur_lines, "version:") or 1
    detail = (f"{breaking_count} breaking change(s) since {base_ver or '?'} require a major bump"
              if not ok else "version bump is consistent with the diffed changes")
    facts.append(Fact("api.contract.versionPolicy",
                      {"ok": ok, "breakingChanges": breaking_count, "majorBumped": major_bumped,
                       "detail": detail, **common},
                      ctx.evidence(cur_rel, ln, ln, "common.openapi"),
                      Symbol(f"version-policy {cur_rel}", "contract-version-policy")))
    return facts


def current_specs(ctx: ScanContext) -> list[str]:
    """Relpaths of the repo's *current* spec files. The baseline dir is excluded — those files are
    only the diff baseline, never the live contract."""
    prefix = BASELINE_DIR + "/"
    return [rel for path in ctx.files(*_SPEC_GLOBS)
            if not (rel := ctx.rel(path)).startswith(prefix)]


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    baselines = _baseline_specs(ctx)
    baseline_prefix = BASELINE_DIR + "/"
    for path in ctx.files(*_SPEC_GLOBS):
        rel = ctx.rel(path)
        if rel.startswith(baseline_prefix):
            continue  # baseline specs are the diff reference only, never the current-spec ingest
        lines = ctx.read_lines(rel)
        data, err = load_yaml_mapping(ctx, rel, "common.openapi")
        if err is not None:
            facts.append(err)
        if data is None:
            continue
        kind = _spec_kind(data)
        if kind is None:
            continue
        version = _spec_version(data)

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
            # Baseline diff (#7 versioning half): only when this spec has a same-named baseline.
            base = baselines.get(path.name)
            if base is not None:
                facts.extend(_diff_facts(ctx, rel, data, base[0], base[1]))
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
