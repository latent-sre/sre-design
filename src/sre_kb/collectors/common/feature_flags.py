"""Feature-flag detector (coverage matrix #15) — Tier-A.

The `FeatureFlag` kind had a schema but no detector. Feature flags are operational toggles a reviewer
must know about (a flag *is* a runtime branch in a flow), so detection is deterministic and
byte-grounded from three sources:

  - **config flag blocks** — a `feature-flags:` / `features:` / `toggles:` map in `application*.yml`,
    one flag per boolean leaf (defaultState from the value);
  - **Spring `@ConditionalOnProperty`** — a config-gated bean is a toggle (name from prefix+name/value,
    defaultState from `matchIfMissing`);
  - **flag-SDK calls** — a call to a known client (LaunchDarkly/Unleash/FF4J/Flagsmith) with a literal
    key (provider inferred from the method; default state is a runtime arg, so `unknown`).

Detection is data (the `_SDK` catalog), mirroring `signatures.py` / `inventory_signatures.py`: a new
provider is a row, not a branch. Emits `feature.flag` facts; `synth/inventory.py` rolls them into
`FeatureFlag` artifacts.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sre_kb.collectors.base import ScanContext, parse_error_fact
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

_LANG = {".java": "java", ".cs": "csharp", ".py": "python",
         ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".go": "go"}

# Config keys whose immediate boolean children are feature flags.
_FLAG_BLOCKS = ("feature-flags", "featureFlags", "features", "toggles", "togglz")

# Flag-SDK call method (lower-cased) -> provider. The first string-literal arg is the flag key.
_SDK = {
    "boolvariation": "launchdarkly", "variation": "launchdarkly", "boolvariationdetail": "launchdarkly",
    "isenabled": "unleash", "isfeatureenabled": "flagsmith", "hasfeature": "flagsmith",
    "check": "ff4j", "getfeature": "ff4j",
}

# Receivers that disambiguate an over-generic method (`variation`, `check`) from a real flag client.
_SDK_RECEIVERS = ("ld", "ldclient", "client", "unleash", "ff4j", "flagsmith", "featuremanager",
                  "featureflags", "flags", "toggles")


def _kill_switch(name: str) -> bool:
    low = name.lower()
    return "kill" in low or "disable" in low or "emergency" in low


def _flag(ctx: ScanContext, rel: str, line: int, name: str, provider: str, default: str) -> Fact:
    return Fact(
        "feature.flag",
        {"name": name, "provider": provider, "defaultState": default, "killSwitch": _kill_switch(name)},
        ctx.evidence(rel, line, line, "common.feature_flags"),
        Symbol(name, "feature-flag"),
    )


def _config_flags(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("application.yml", "application.yaml", "application-*.yml"):
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = yaml.safe_load(ctx.read_text(rel)) or {}
        except yaml.YAMLError as exc:
            facts.append(parse_error_fact(ctx, rel, "common.feature_flags", exc))
            continue
        if not isinstance(data, dict):
            continue
        for block in _FLAG_BLOCKS:
            flags = data.get(block)
            if not isinstance(flags, dict):
                continue
            block_ln = find_line(lines, f"{block}:") or 1
            for name, val in flags.items():
                if not isinstance(val, bool):
                    continue  # only boolean leaves are flags (a nested map is structure, not a toggle)
                ln = find_line(lines, f"{name}:", block_ln) or block_ln
                facts.append(_flag(ctx, rel, ln, str(name), "config", "on" if val else "off"))
    return facts


def _conditional_on_property(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        module = ctx.module(rel, "java")
        for t in module.types:
            for holder, line in [(t.annotations, t.start)] + [(m.annotations, m.name_line) for m in t.methods]:
                args = holder.get("@ConditionalOnProperty")
                if args is None:
                    continue
                prefix, name = args.get("prefix", ""), args.get("name") or args.get("value") or ""
                flag = f"{prefix}.{name}".strip(".") if prefix else name
                if not flag:
                    continue
                default = "on" if str(args.get("matchIfMissing", "")).lower() == "true" else "off"
                facts.append(_flag(ctx, rel, line, flag, "spring-config", default))
    return facts


def _sdk_flags(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java", "*.cs", "*.py", "*.js", "*.mjs", "*.cjs", "*.go"):
        rel = ctx.rel(path)
        lang = _LANG.get(Path(rel).suffix)
        if lang is None:
            continue
        module = ctx.module(rel, lang)
        for t in module.types:
            for m in t.methods:
                for c in m.calls:
                    provider = _SDK.get(c.method.lower())
                    if provider is None or not c.str_args:
                        continue
                    if c.receiver and c.receiver.lower() not in _SDK_RECEIVERS:
                        continue  # a generic method name on a non-flag receiver is not a flag check
                    facts.append(_flag(ctx, rel, c.line, c.str_args[0], provider, "unknown"))
    return facts


def collect(ctx: ScanContext) -> list[Fact]:
    """Self-gating: a repo with no flag config / annotation / SDK call emits nothing. De-duplicate by
    flag name (a flag declared in config AND read via an SDK is one flag), preferring the source that
    knows a concrete default state over an `unknown` SDK read."""
    by_name: dict[str, Fact] = {}
    for fact in _config_flags(ctx) + _conditional_on_property(ctx) + _sdk_flags(ctx):
        name = fact.attrs["name"]
        prior = by_name.get(name)
        if prior is None or (prior.attrs["defaultState"] == "unknown" and fact.attrs["defaultState"] != "unknown"):
            by_name[name] = fact
    return list(by_name.values())
