"""Resilience4j parameter-completeness gaps (HYBRID-PLAN Round-3 R5) — Tier-A recall.

A resilience pattern can be *present* (annotation declared) yet under-specified: a `@CircuitBreaker`
with no `failure-rate-threshold`, or a `@Retry` with no `wait-duration`/backoff (retry-storm risk).
These are deterministic, byte-grounded gaps — the engine asserts them from the annotation plus the
*resolved* resilience4j config, with no LLM. They are the Tier-A **parameter-completeness** dual of
the Tier-B absence gaps, and a natural graduation target (§7.9): the LLM finds a category, a human
confirms, and a deterministic rule like this one takes it over.

Scope: resilience4j (Spring), whose params live in config. (.NET/Polly configures inline in code — a
separate future probe.) Timeout-duration completeness is deferred: a `@TimeLimiter` has a library
default, and the Tier-B `missing-timeout` probe already covers timeout *absence* at the call site.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext, load_yaml_mapping
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import dig, fqn

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
                    if any(_configured(data, section, name, tokens) for _, data in configs):
                        continue  # the param is configured somewhere applicable — not a gap
                    target_sym = fqn(ns, t.name, m.name)
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
