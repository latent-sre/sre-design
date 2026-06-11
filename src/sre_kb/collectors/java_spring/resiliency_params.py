"""Resilience4j parameter-completeness + disabled-mechanism gaps (HYBRID-PLAN Round-3 R5 /
S4c) — Tier-A recall.

A resilience pattern can be *present* (annotation declared) yet under-specified: a `@CircuitBreaker`
with no `failure-rate-threshold`, or a `@Retry` with no `wait-duration`/backoff (retry-storm risk).
These are deterministic, byte-grounded gaps — the engine asserts them from the annotation plus the
*resolved* resilience4j config, with no LLM. They are the Tier-A **parameter-completeness** dual of
the Tier-B absence gaps, and a natural graduation target (§7.9): the LLM finds a category, a human
confirms, and a deterministic rule like this one takes it over.

The same resolution also powers the **proactive disable probe** (S4c's graduation of
`disabled-resilience`): a declared mechanism whose resolved config explicitly sets
`enabled: false` does not protect the call — the same conservative explicit-toggle rule the
confirm loop re-grounds when a reviewer disputes a presence claim (`pipeline/confirm.py`
`_DISABLE_RE`), now run without anyone pointing first. A disabled mechanism dominates its
parameter gaps (tuning a breaker that is off is moot).

Scope: resilience4j (Spring), whose params live in config. (.NET/Polly configures inline in code — a
separate future probe.) Timeout-duration completeness is deferred: a `@TimeLimiter` has a library
default, and the Tier-B `missing-timeout` probe already covers timeout *absence* at the call site.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext, load_yaml_mapping
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import dig, find_line, fqn

_CONFIG_GLOBS = ("application.yml", "application.yaml", "application-*.yml")

# (annotation, resilience4j config section, normalized param tokens that count as "configured",
#  gap category, severity, human-readable param, the risk if it is left to the library default).
_SPECS = (
    (
        "@CircuitBreaker",
        "circuitbreaker",
        ("failureratethreshold",),
        "circuit-breaker-without-thresholds",
        "medium",
        "failure-rate-threshold",
        "the breaker trips on the resilience4j default threshold, unreviewed against this service",
    ),
    (
        "@Retry",
        "retry",
        ("waitduration", "backoff", "intervalfunction"),
        "retry-without-backoff",
        "high",
        "wait-duration/backoff",
        "retries with no explicit backoff risk a retry storm against the dependency",
    ),
)


def _norm(key: str) -> str:
    """Normalize a config key so relaxed binding variants compare equal (Spring accepts
    `failure-rate-threshold`, `failureRateThreshold`, `failure_rate_threshold`)."""
    return key.replace("-", "").replace("_", "").lower()


def _block_has(block: object, tokens: tuple[str, ...]) -> bool:
    return isinstance(block, dict) and any(any(t in _norm(str(k)) for t in tokens) for k in block)


def _configured(data: dict, section: str, name: str, tokens: tuple[str, ...]) -> bool:
    """True iff `name`'s resolved resilience4j config sets a matching param — checking the instance
    block, its explicit `base-config`, and (only when none is set) the implicit `configs.default`."""
    sec = dig(data, "resilience4j", section)
    if not isinstance(sec, dict):
        return False
    instances = sec.get("instances") if isinstance(sec.get("instances"), dict) else {}
    configs = sec.get("configs") if isinstance(sec.get("configs"), dict) else {}
    inst = instances.get(name) if isinstance(instances.get(name), dict) else {}
    if _block_has(inst, tokens):
        return True
    base = inst.get("base-config") or inst.get("baseConfig")
    if base:
        return _block_has(
            configs.get(base), tokens
        )  # an explicit base-config overrides the default
    return _block_has(
        configs.get("default"), tokens
    )  # resilience4j applies configs.default otherwise


def _enabled_value(block: object) -> bool | None:
    """The block's explicit `enabled` toggle (relaxed-binding key), or None when unset."""
    if not isinstance(block, dict):
        return None
    for k, v in block.items():
        if _norm(str(k)) == "enabled":
            return not (v is False or str(v).strip().lower() == "false")
    return None


def _disabled(data: dict, section: str, name: str) -> bool:
    """True iff `name`'s *resolved* resilience4j config explicitly disables it: the instance's
    own `enabled` decides outright; otherwise the explicit `base-config` (or the implicit
    `configs.default`) is inherited — the same explicit-toggle conservatism as the confirm
    loop's `_DISABLE_RE`, never inferred."""
    sec = dig(data, "resilience4j", section)
    if not isinstance(sec, dict):
        return False
    instances = sec.get("instances") if isinstance(sec.get("instances"), dict) else {}
    configs = sec.get("configs") if isinstance(sec.get("configs"), dict) else {}
    inst = instances.get(name) if isinstance(instances.get(name), dict) else {}
    own = _enabled_value(inst)
    if own is not None:
        return not own
    base = inst.get("base-config") or inst.get("baseConfig")
    inherited = _enabled_value(configs.get(base)) if base else _enabled_value(configs.get("default"))
    return inherited is False


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    configs: list[tuple[str, dict]] = []
    for path in ctx.files(*_CONFIG_GLOBS):
        rel = ctx.rel(path)
        data, err = load_yaml_mapping(ctx, rel, "java_spring.resiliency_params")
        if err is not None:
            facts.append(err)
        if data is not None:
            configs.append((rel, data))
    checked = [rel for rel, _ in configs]

    disabled_seen: set[tuple[str, str]] = set()
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        module = ctx.module(rel, "java")
        ns = module.namespace
        for t in module.types:
            for m in t.methods:
                for ann, section, tokens, category, severity, param, risk in _SPECS:
                    if ann not in m.annotations:
                        continue
                    name = m.annotations[ann].get("name") or m.name
                    target_sym = fqn(ns, t.name, m.name)
                    disabling = next(
                        (rel_cfg for rel_cfg, data in configs if _disabled(data, section, name)),
                        None)
                    if disabling:
                        # S4c proactive disable probe: cite the disabling config line. A
                        # disabled mechanism dominates its parameter gaps.
                        if (section, name) in disabled_seen:
                            continue
                        disabled_seen.add((section, name))
                        cfg_lines = ctx.read_lines(disabling)
                        inst_ln = find_line(cfg_lines, name) or 1
                        ln = find_line(cfg_lines, "enabled", inst_ln) or inst_ln
                        facts.append(
                            Fact(
                                "resiliency.gap",
                                {
                                    "category": "disabled-resilience",
                                    "target": name,
                                    "severity": "high",
                                    "rationale": (
                                        f"{ann}('{name}') is declared but its resolved config "
                                        "disables it (enabled: false) — it does not protect "
                                        "the call."
                                    ),
                                    "rederivation": "disabled",
                                    "checked": checked,
                                },
                                ctx.evidence(
                                    disabling, ln, ln, "java_spring.resiliency_params"
                                ),
                                Symbol(target_sym, "method"),
                            )
                        )
                        continue
                    if any(_configured(data, section, name, tokens) for _, data in configs):
                        continue  # the param is configured somewhere applicable — not a gap
                    facts.append(
                        Fact(
                            "resiliency.gap",
                            {
                                "category": category,
                                "target": name,
                                "severity": severity,
                                "rationale": (
                                    f"{ann}('{name}') declares the pattern but no {param} is "
                                    f"configured for it — {risk}."
                                ),
                                "rederivation": "param-completeness",
                                "checked": checked,
                            },
                            ctx.evidence(
                                rel, m.start, m.name_line, "java_spring.resiliency_params"
                            ),
                            Symbol(target_sym, "method"),
                        )
                    )
    return facts
