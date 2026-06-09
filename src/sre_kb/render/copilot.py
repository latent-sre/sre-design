"""Copilot projections: reliability-guardrail instructions + runbook markdown.

The guardrails turn the KB into rules that make Copilot *preserve* reliability when
editing code (not just document it).
"""

from __future__ import annotations

from sre_kb.render.diagrams import mermaid_sequence
from sre_kb.render.templating import inline as _inline
from sre_kb.render.templating import render
from sre_kb.tiers import AST, LLM, artifact_tier

GENERATED = "<!-- GENERATED from SRE KB — edit the KB, not this file. -->"


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


def _flow_line(f: dict) -> dict:
    """A Critical-flows entry: name plus its trigger as a single `METHOD path` line (rstripped so a
    missing path/method leaves no trailing space). `name` stays raw — the template's `inline` filter
    sanitizes it where it's rendered."""
    t = f["spec"].get("trigger", {})
    return {
        "name": f["metadata"]["name"],
        "line": f"{_inline(t.get('method', ''))} {_inline(t.get('path', ''))}".rstrip(),
    }


def copilot_instructions(service: str, docs: list[dict]) -> str:
    flows = [_flow_line(d) for d in docs if d["kind"] == "Flow"]
    out = render(
        "copilot-instructions.md.j2",
        generated=GENERATED,
        service=service,
        rules=reliability_guardrails(docs),
        advisories=advisory_notes(docs),
        flows=flows,
    )
    # The document always ends in exactly one trailing newline (parity with the prior renderer).
    return out.rstrip("\n") + "\n"


def runbook_markdown(runbook: dict, flow: dict | None) -> str:
    spec = runbook.get("spec", {})
    name = runbook["metadata"]["name"]
    out = render(
        "runbook.md.j2",
        generated=GENERATED,
        name=name,
        banner=spec.get("banner", "GENERATED — verify before executing"),
        alert_ref=spec.get("trigger", {}).get("alertRef", _inline(name)),
        related_flow=spec.get("relatedFlow", "-"),
        escalation=spec.get("escalation", "-"),
        symptoms=spec.get("symptoms", []),
        # Diagnosis items may be {"step": ...} dicts or plain strings (hand/LLM-authored).
        diagnosis=[d.get("step", "") if isinstance(d, dict) else d for d in spec.get("diagnosis", [])],
        remediation=spec.get("remediation", []),
        flow_diagram=mermaid_sequence(flow) if flow is not None else None,
    )
    # A flow appends a trailing-newline section; the no-flow form ends on the last list item with no
    # trailing newline (parity with the prior renderer).
    return out.rstrip("\n") + ("\n" if flow is not None else "")
