"""Copilot projections: reliability-guardrail instructions + runbook markdown.

The guardrails turn the KB into rules that make Copilot *preserve* reliability when
editing code (not just document it).
"""

from __future__ import annotations

from sre_kb.render.diagrams import mermaid_sequence

GENERATED = "<!-- GENERATED from SRE KB — edit the KB, not this file. -->"


def reliability_guardrails(docs: list[dict]) -> list[str]:
    rules: list[str] = []
    for d in docs:
        spec = d.get("spec", {})
        if d["kind"] == "ResiliencyPattern" and spec.get("type") == "circuit-breaker":
            tgt = spec.get("targetSymbol", "the protected call")
            rules.append(
                f"Preserve the circuit breaker on `{tgt}` (and its timeout). Do not remove "
                f"`@CircuitBreaker`/`@TimeLimiter` or widen timeouts without an SLO review."
            )
        if d["kind"] == "Fallback":
            rules.append(
                f"Keep the fallback `{spec.get('fallbackSymbol')}` for "
                f"`{spec.get('forTarget')}` — the degraded path is intentional."
            )
        if d["kind"] == "Flow":
            for s in spec.get("steps", []):
                if any(fm.get("dataLossRisk") for fm in s.get("failureModes", [])):
                    rules.append(
                        f"Step `{s['name']}` loses data on failure (fire-and-forget publish). "
                        f"Do NOT swallow the exception; add an outbox/retry instead of hiding it."
                    )
    # de-dup, preserve order
    seen: set[str] = set()
    return [r for r in rules if not (r in seen or seen.add(r))]


def copilot_instructions(service: str, docs: list[dict]) -> str:
    flows = [d for d in docs if d["kind"] == "Flow"]
    lines = [
        GENERATED,
        f"# SRE guardrails for `{service}`",
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
            lines.append(f"- `{f['metadata']['name']}` — {t.get('method','')} {t.get('path','')}")
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
    name = runbook["metadata"]["name"]
    lines = [
        GENERATED,
        f"# Runbook: {name}",
        "",
        f"> {spec.get('banner', 'GENERATED — verify before executing')}",
        "",
        f"**Trigger:** alert `{spec.get('trigger', {}).get('alertRef', name)}`  ",
        f"**Related flow:** `{spec.get('relatedFlow', '-')}`  ",
        f"**Escalation:** {spec.get('escalation', '-')}",
        "",
        "## Symptoms",
    ]
    lines += [f"- {s}" for s in spec.get("symptoms", [])] or ["- (none)"]
    lines += ["", "## Diagnosis"]
    lines += [f"1. {d.get('step', d)}" for d in spec.get("diagnosis", [])] or ["1. (none)"]
    lines += ["", "## Remediation"]
    lines += [f"1. {r}" for r in spec.get("remediation", [])] or ["1. (none)"]
    if flow is not None:
        lines += ["", "## Flow", "", "```mermaid", mermaid_sequence(flow), "```", ""]
    return "\n".join(lines)
