"""Copilot projections: reliability-guardrail instructions + runbook markdown.

The guardrails turn the KB into rules that make Copilot *preserve* reliability when
editing code (not just document it).
"""

from __future__ import annotations

import re

from sre_kb.render.diagrams import mermaid_sequence
from sre_kb.tiers import AST, LLM, artifact_tier

GENERATED = "<!-- GENERATED from SRE KB — edit the KB, not this file. -->"


def _inline(text: object) -> str:
    """Flatten a value to one safe line before it lands in a guardrail/runbook: collapse
    whitespace (kills newline-injected bullets/instructions) and drop backticks (kills
    code-span breakout). Guardrails are rules the developer is told to obey, so an injected
    line must never masquerade as one."""
    return re.sub(r"\s+", " ", str(text)).replace("`", "").strip()


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return [x for x in items if not (x in seen or seen.add(x))]


def _rules_for(d: dict) -> list[str]:
    """The reliability rule(s) a single artifact implies (tier-agnostic text)."""
    spec = d.get("spec", {})
    out: list[str] = []
    if d["kind"] == "ResiliencyPattern" and spec.get("type") == "circuit-breaker":
        tgt = _inline(spec.get("targetSymbol", "the protected call"))
        out.append(
            f"Preserve the circuit breaker on `{tgt}` (and its timeout). Do not remove "
            f"`@CircuitBreaker`/`@TimeLimiter` or widen timeouts without an SLO review."
        )
    if d["kind"] == "Fallback":
        out.append(
            f"Keep the fallback `{_inline(spec.get('fallbackSymbol'))}` for "
            f"`{_inline(spec.get('forTarget'))}` — the degraded path is intentional."
        )
    if d["kind"] == "Flow":
        for s in spec.get("steps", []):
            if any(fm.get("dataLossRisk") for fm in s.get("failureModes", [])):
                out.append(
                    f"Step `{_inline(s['name'])}` loses data on failure (fire-and-forget "
                    f"publish). Do NOT swallow the exception; add an outbox/retry instead "
                    f"of hiding it."
                )
    return out


def reliability_guardrails(docs: list[dict]) -> list[str]:
    """Hard reliability rules — Tier-A (byte-grounded) artifacts only. The blast radius of an
    LLM mistake must never be a hard editor rule (HYBRID-PLAN §7.2); Tier-B findings surface
    as advisory notes instead (see `advisory_notes`)."""
    rules = [r for d in docs if artifact_tier(d) == AST for r in _rules_for(d)]
    return _dedup(rules)


def advisory_notes(docs: list[dict]) -> list[str]:
    """Tier-B (LLM-proposed, not byte-grounded) findings, surfaced as advisories — never hard
    rules (HYBRID-PLAN §7.2)."""
    notes = [
        f"{r}  (LLM-proposed — verify against the code; not byte-grounded.)"
        for d in docs if artifact_tier(d) == LLM for r in _rules_for(d)
    ]
    return _dedup(notes)


def copilot_instructions(service: str, docs: list[dict]) -> str:
    flows = [d for d in docs if d["kind"] == "Flow"]
    lines = [
        GENERATED,
        f"# SRE guardrails for `{_inline(service)}`",
        "",
        "This service has a validated SRE knowledge base. When editing code here, respect:",
        "",
        "## Reliability guardrails",
    ]
    rules = reliability_guardrails(docs)
    lines += [f"- {r}" for r in rules] or ["- (none detected)"]
    advisories = advisory_notes(docs)
    if advisories:
        lines += [
            "",
            "## Advisory (LLM-proposed, unverified)",
            "Not byte-grounded — verify before acting; do not enforce these as hard rules.",
        ]
        lines += [f"- {a}" for a in advisories]
    if flows:
        lines += ["", "## Critical flows"]
        for f in flows:
            t = f["spec"].get("trigger", {})
            lines.append(
                f"- `{_inline(f['metadata']['name'])}` — "
                f"{_inline(t.get('method',''))} {_inline(t.get('path',''))}".rstrip()
            )
    lines += [
        "",
        "## Conventions",
        "- Every reliability claim in the KB cites `path:line`; keep code and KB in sync.",
        "- Treat generated runbooks as drafts: verify before executing during an incident.",
        "",
    ]
    return "\n".join(lines)


def runbook_markdown(runbook: dict, flow: dict | None) -> str:
    spec = runbook.get("spec", {})
    name = _inline(runbook["metadata"]["name"])
    lines = [
        GENERATED,
        f"# Runbook: {name}",
        "",
        f"> {_inline(spec.get('banner', 'GENERATED — verify before executing'))}",
        "",
        f"**Trigger:** alert `{_inline(spec.get('trigger', {}).get('alertRef', name))}`  ",
        f"**Related flow:** `{_inline(spec.get('relatedFlow', '-'))}`  ",
        f"**Escalation:** {_inline(spec.get('escalation', '-'))}",
        "",
        "## Symptoms",
    ]
    lines += [f"- {_inline(s)}" for s in spec.get("symptoms", [])] or ["- (none)"]
    lines += ["", "## Diagnosis"]
    lines += [f"1. {_inline(d.get('step', d))}" for d in spec.get("diagnosis", [])] or ["1. (none)"]
    lines += ["", "## Remediation"]
    lines += [f"1. {_inline(r)}" for r in spec.get("remediation", [])] or ["1. (none)"]
    if flow is not None:
        lines += ["", "## Flow", "", "```mermaid", mermaid_sequence(flow), "```", ""]
    return "\n".join(lines)
