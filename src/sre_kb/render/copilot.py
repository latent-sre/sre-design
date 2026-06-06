"""Copilot projections: reliability-guardrail instructions + runbook markdown.

The guardrails turn the KB into rules that make Copilot *preserve* reliability when
editing code (not just document it).
"""

from __future__ import annotations

import re

from sre_kb.render.diagrams import mermaid_sequence

GENERATED = "<!-- GENERATED from SRE KB — edit the KB, not this file. -->"


def _inline(text: object) -> str:
    """Flatten a value to one safe line before it lands in a guardrail/runbook: collapse
    whitespace (kills newline-injected bullets/instructions) and drop backticks (kills
    code-span breakout). Guardrails are rules the developer is told to obey, so an injected
    line must never masquerade as one."""
    return re.sub(r"\s+", " ", str(text)).replace("`", "").strip()


def reliability_guardrails(docs: list[dict]) -> list[str]:
    rules: list[str] = []
    for d in docs:
        spec = d.get("spec", {})
        if d["kind"] == "ResiliencyPattern" and spec.get("type") == "circuit-breaker":
            tgt = _inline(spec.get("targetSymbol", "the protected call"))
            rules.append(
                f"Preserve the circuit breaker on `{tgt}` (and its timeout). Do not remove "
                f"`@CircuitBreaker`/`@TimeLimiter` or widen timeouts without an SLO review."
            )
        if d["kind"] == "Fallback":
            rules.append(
                f"Keep the fallback `{_inline(spec.get('fallbackSymbol'))}` for "
                f"`{_inline(spec.get('forTarget'))}` — the degraded path is intentional."
            )
        if d["kind"] == "Flow":
            for s in spec.get("steps", []):
                if any(fm.get("dataLossRisk") for fm in s.get("failureModes", [])):
                    rules.append(
                        f"Step `{_inline(s['name'])}` loses data on failure (fire-and-forget "
                        f"publish). Do NOT swallow the exception; add an outbox/retry instead "
                        f"of hiding it."
                    )
    # de-dup, preserve order
    seen: set[str] = set()
    return [r for r in rules if not (r in seen or seen.add(r))]


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
