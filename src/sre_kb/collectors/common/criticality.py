"""Criticality collector (HYBRID-PLAN Round-3 R1) — service criticality + data classification.

Two trust paths, both byte-grounded:

  declared    — an authoritative repo-local declaration (`.sre/criticality.yaml`: tier /
                businessCriticality / dataClassification) is read and cited to its own line
                (Tier-A). This is the floor-eligible tier (R2): a *grounded* tier deterministically
                raises alert severity. A Tier-B `.sre/criticality-proposal.yaml` (written by the
                `assess-criticality-and-data` skill, R3) is read the same way but stamped
                `source_tier=llm`, so it lands needs-review and never feeds the severity floor —
                only a grounded tier does (the §7.2 advisory-vs-hard-rule boundary).

  dataclass   — PII/PCI signals in code (`email`, `ssn`, `cardNumber`, …) are detected
                deterministically and emitted one `criticality.dataclass` fact per classification,
                cited to the first matching line. This is the deterministic core: a data
                classification the engine can prove, not an LLM assertion.

Self-gating: no declaration and no PII/PCI signal -> no facts (inert on a plain repo).
"""

from __future__ import annotations

import re

import yaml

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.tiers import AST, LLM

# Authoritative declaration (Tier-A) vs Copilot proposal (Tier-B). Catalog beats proposal.
_DECL_REL = ".sre/criticality.yaml"
_PROPOSAL_REL = ".sre/criticality-proposal.yaml"

_SOURCE_GLOBS = ("*.java", "*.cs", "*.py")

# PII/PCI data-classification signatures: a field/annotation name -> classification. Conservative on
# purpose (a false PII claim is worse than a miss; the gap is widened by the Tier-B skill, not by
# loosening these). Matched as whole tokens so `panel` does not match `pan`, `emailed` does match
# `email` only via the word stem we allow below.
_CLASS_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    "pci": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bcard[_-]?(?:number|holder)\b",
            r"\bcredit[_-]?card\b",
            r"\bcvv\b",
            r"\bcvc\b",
            r"\bpan\b",  # primary account number (whole token; 'panel' is not a match)
        )
    ),
    "pii": tuple(
        re.compile(p, re.I)
        for p in (
            r"\bemail\b",
            r"@Email\b",
            r"\bssn\b",
            r"\bsocial[_-]?security\b",
            r"\bpassport\b",
            r"\bdate[_-]?of[_-]?birth\b",
            r"\bdob\b",
            r"\bphone[_-]?number\b",
            r"\btax[_-]?id\b",
        )
    ),
}


def _key_line(lines: list[str], key: str) -> int:
    """1-based line where a top-level YAML `key:` is declared (the most load-bearing line to cite)."""
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith(f"{key}:"):
            return i
    return 1


def _declared(ctx: ScanContext, rel: str, source_tier: str) -> Fact | None:
    """Read a criticality declaration file into a `criticality.declared` fact, cited to its `tier:`
    line. `source_tier` distinguishes the authoritative file (ast) from a Copilot proposal (llm)."""
    if not (ctx.root / rel).is_file():
        return None
    try:
        doc = yaml.safe_load(ctx.read_text(rel)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(doc, dict):
        return None
    tier = str(doc.get("tier") or "unknown")
    attrs = {
        "tier": tier,
        "businessCriticality": str(doc.get("businessCriticality") or "unknown"),
        "source": str(doc.get("source") or ("inferred" if source_tier == LLM else "human-input")),
    }
    dc = doc.get("dataClassification")
    if isinstance(dc, list) and dc:
        attrs["dataClassification"] = [str(x) for x in dc]
    line = _key_line(ctx.read_lines(rel), "tier")
    return Fact(
        "criticality.declared",
        attrs,
        ctx.evidence(rel, line, line, "common.criticality", source_tier=source_tier),
        Symbol(rel, "config-key"),
    )


def _data_classes(ctx: ScanContext) -> list[Fact]:
    """One `criticality.dataclass` fact per detected classification, cited to the first hit (Tier-A
    — a data classification the engine can prove from the bytes)."""
    facts: list[Fact] = []
    for classification, patterns in _CLASS_PATTERNS.items():
        hit: tuple[str, int] | None = None
        for path in ctx.files(*_SOURCE_GLOBS):
            rel = ctx.rel(path)
            for i, ln in enumerate(ctx.read_lines(rel), 1):
                if any(p.search(ln) for p in patterns):
                    hit = (rel, i)
                    break
            if hit:
                break
        if hit:
            rel, line = hit
            facts.append(
                Fact(
                    "criticality.dataclass",
                    {"classification": classification},
                    ctx.evidence(rel, line, line, "common.criticality"),
                    Symbol(f"{rel}:{line}", "config-key"),
                )
            )
    return facts


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    # An authoritative declaration wins over a Copilot proposal (never read both).
    declared = _declared(ctx, _DECL_REL, AST) or _declared(ctx, _PROPOSAL_REL, LLM)
    if declared is not None:
        facts.append(declared)
    facts.extend(_data_classes(ctx))
    return facts
