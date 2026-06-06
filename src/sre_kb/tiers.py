"""Trust-tier helpers shared across the pipeline, render, reporting, and publish layers.

A piece of evidence carries a `source_tier` (Phase 0): "ast" (deterministic, byte-grounded;
Tier-A) or "llm" (LLM-proposed; Tier-B). An artifact's tier rolls that up — it is "llm" if any
cited evidence is Tier-B, else "ast". Consumers gate on this: only Tier-A findings emit hard
editor guardrails (HYBRID-PLAN §7.2), and human-facing output labels each claim by tier (§7.5).
"""

from __future__ import annotations

AST = "ast"
LLM = "llm"

_LABELS = {AST: "AST-grounded", LLM: "LLM-proposed"}


def artifact_tier(doc: dict) -> str:
    """Roll an artifact's trust tier up from its evidence: "llm" if any cited evidence is
    Tier-B, else "ast" (also the default for evidence-free artifacts)."""
    tiers = {(ev or {}).get("source_tier", AST) for ev in (doc.get("evidence") or [])}
    return LLM if LLM in tiers else AST


def tier_label(tier: str) -> str:
    """Human-facing label for a tier (HYBRID-PLAN §7.5)."""
    return _LABELS.get(tier, tier)
