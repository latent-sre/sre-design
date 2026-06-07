"""LLM gap-finder (HYBRID-PLAN §7.9/§7.10) — the first Tier-B collector.

An LLM (Copilot, running the vendored `assess-resiliency` skill — see
`.github/skills/sre-gap-finder/`) reads the engine's facts + the code and proposes resiliency
*gaps* the AST missed: e.g. a critical client call with no timeout. Each proposal quotes the
verbatim excerpt it points at, NOT a line number.

This module is the engine half of the non-circular contract:

  locate    — the engine finds the proposed excerpt in the bytes itself; a quote it can't find
              verbatim is dropped (no fabricated citations).
  stamp     — the engine emits `ctx.evidence(..., source_tier="llm")` over the located lines, so
              the citation is hash-checkable like any other.
  re-derive — the engine runs a deterministic *refutation probe* with the SAME shared
              `signatures` library Tier-A keys off. For a missing-timeout gap: there must be an
              outbound client call in scope AND the `timeout` signature must NOT fire anywhere the
              engine checked (the enclosing type + config). If it fires, the gap is refuted and
              dropped — the LLM cannot assert a gap that isn't there.

Only refutation-surviving gaps become facts. Each carries `source_tier="llm"`, the honest list of
places the engine `checked`, and lands `needs-review` downstream — nothing here auto-verifies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.parsing import parse
from sre_kb.signatures import fires
from sre_kb.tiers import LLM

# Conventional location of the LLM's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/gap-proposals.json"

_EXT_LANG = {".java": "java", ".cs": "csharp"}
_SOURCE_GLOBS = ("*.java", "*.cs")
# Config files the timeout refutation probe also searches (a timeout may live in config, not code).
_CONFIG_GLOBS = ("application.yml", "application.yaml", "application*.properties",
                 "appsettings*.json", "bootstrap.yml")

# Outbound-client call names — the receiver of a remote dependency call that ought to carry a
# timeout (Java RestTemplate/WebClient; C# HttpClient).
_CLIENT_METHODS = {
    "getforobject", "postforobject", "putforobject", "patchforobject", "deleteforobject",
    "getforentity", "postforentity", "exchange", "execute", "retrieve", "bodytomono",
    "getasync", "postasync", "putasync", "deleteasync", "patchasync", "sendasync",
}

# Gap categories that have a deterministic refutation probe in this spike. Others from the §7.9
# taxonomy are recorded as proposals but not asserted (no engine probe yet → can't ground).
_REFUTABLE = {"missing-timeout": "timeout"}


@dataclass(frozen=True)
class Proposal:
    """One gap hypothesis from the LLM. `anchor` is excerpt TEXT, never a line number."""

    category: str
    anchor: str
    target: str | None = None
    severity: str = "medium"
    rationale: str | None = None


@dataclass
class Outcome:
    """Per-proposal audit trail — the go/no-go evidence for whether the tier is noisy."""

    proposal: Proposal
    result: str  # confirmed | refuted | unlocatable | unconfirmable
    path: str | None = None
    lines: tuple[int, int] | None = None
    checked: tuple[str, ...] = ()
    note: str = ""


@dataclass
class GapResult:
    facts: list[Fact] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)

    def confirmed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.result == "confirmed"]

    def dropped(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.result != "confirmed"]


# --------------------------------------------------------------------------- loading

def load_proposals(path: Path) -> list[Proposal]:
    """Parse a Copilot-produced proposals file (a bare list or {"proposals": [...]})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("proposals", []) if isinstance(data, dict) else data
    out: list[Proposal] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        anchor = str(it.get("anchor") or it.get("excerpt") or "").strip()
        category = str(it.get("category") or it.get("pattern") or "").strip().lower()
        if not anchor or not category:
            continue  # a typeless/anchorless proposal can't be grounded
        out.append(Proposal(
            category=category,
            anchor=anchor,
            target=(str(it["target"]) if it.get("target") else None),
            severity=str(it.get("severity") or "medium").strip().lower(),
            rationale=(str(it["rationale"]) if it.get("rationale") else None),
        ))
    return out


# --------------------------------------------------------------------------- locate

def _locate(ctx: ScanContext, anchor: str) -> tuple[str, int, int] | None:
    """Find the verbatim anchor as a contiguous run of whole source lines. Returns
    (relpath, start, end) 1-based inclusive, or None if it isn't present verbatim."""
    needles = [ln.strip() for ln in anchor.splitlines() if ln.strip()]
    if not needles:
        return None
    for path in ctx.files(*_SOURCE_GLOBS):
        rel = ctx.rel(path)
        stripped = [ln.strip() for ln in ctx.read_lines(rel)]
        for i in range(len(stripped) - len(needles) + 1):
            if all(needles[k] in stripped[i + k] for k in range(len(needles))):
                return rel, i + 1, i + len(needles)
    return None


# --------------------------------------------------------------------------- re-derive

def _enclosing_type(ctx: ScanContext, rel: str, start: int, end: int):
    """Parse `rel`; return (TypeDecl, MethodDecl|None, type_text) enclosing the cited lines, or
    None if the file can't be parsed for re-derivation."""
    lang = _EXT_LANG.get(Path(rel).suffix)
    if lang is None:
        return None
    module = parse(lang, ctx.read_text(rel))
    typedecl = next((t for t in module.types if t.start <= start and t.end >= end), None)
    if typedecl is None:
        return None
    method = next((m for m in typedecl.methods if m.start <= start and m.end >= end), None)
    text = "".join(ctx.read_lines(rel)[typedecl.start - 1 : typedecl.end])
    return typedecl, method, text


def _has_client_call(typedecl, method) -> bool:
    scope = [method] if method else typedecl.methods
    return any(c.method.lower() in _CLIENT_METHODS for m in scope for c in m.calls)


def _config_texts(ctx: ScanContext) -> list[tuple[str, str]]:
    return [(ctx.rel(p), ctx.read_text(ctx.rel(p))) for p in ctx.files(*_CONFIG_GLOBS)]


def _rederive(ctx: ScanContext, rel: str, start: int, end: int, category: str):
    """Deterministic refutation probe for `category` at the cited bytes, using the shared
    `signatures` library. Returns (verdict, checked, note)."""
    concern = _REFUTABLE[category]
    parsed = _enclosing_type(ctx, rel, start, end)
    if parsed is None:
        return "unconfirmable", (rel,), "could not parse an enclosing type at the cited location"
    typedecl, method, type_text = parsed
    if not _has_client_call(typedecl, method):
        return "unconfirmable", (rel,), "no outbound client call at the cited location to ground the gap"

    checked = [rel]
    # The signature firing anywhere the engine looked refutes the absence.
    if fires(concern, type_text):
        return "refuted", (rel,), f"the {concern} signature fires in scope — the gap does not hold"
    for cpath, ctext in _config_texts(ctx):
        checked.append(cpath)
        if fires(concern, ctext):
            return "refuted", tuple(checked), f"the {concern} signature fires in {cpath} — the gap does not hold"
    return "confirmed", tuple(checked), f"no {concern} signature fires in {len(checked)} checked location(s)"


# --------------------------------------------------------------------------- collect

def collect_from_proposals(ctx: ScanContext, proposals: list[Proposal]) -> GapResult:
    """The collector: locate → stamp → re-derive every proposal. Emits one `resiliency.gap` Fact
    per surviving gap; records an Outcome for all (incl. drops) as audit evidence."""
    res = GapResult()
    for p in proposals:
        loc = _locate(ctx, p.anchor)
        if loc is None:
            res.outcomes.append(Outcome(p, "unlocatable", note="anchor not found verbatim in the source"))
            continue
        rel, s, e = loc
        if p.category not in _REFUTABLE:
            res.outcomes.append(Outcome(p, "unconfirmable", rel, (s, e),
                                        note=f"no deterministic refutation probe for category '{p.category}'"))
            continue
        verdict, checked, note = _rederive(ctx, rel, s, e, p.category)
        if verdict != "confirmed":
            res.outcomes.append(Outcome(p, verdict, rel, (s, e), checked, note))
            continue
        target = p.target or Path(rel).stem
        res.facts.append(Fact(
            "resiliency.gap",
            {"category": p.category, "target": target, "severity": p.severity,
             "rationale": p.rationale, "rederivation": "confirmed", "checked": list(checked), "note": note},
            ctx.evidence(rel, s, e, "llm.gap_finder", source_tier=LLM),
            Symbol(f"{rel}:{s}-{e}", "gap"),
        ))
        res.outcomes.append(Outcome(p, "confirmed", rel, (s, e), checked, note))
    return res


def collect(ctx: ScanContext, proposals_path: Path | None = None) -> GapResult:
    """Self-gating entry point: read proposals from `proposals_path` (default the conventional
    in-repo location). No proposals file → empty result."""
    path = proposals_path or (ctx.root / PROPOSALS_REL)
    if not path.exists():
        return GapResult()
    return collect_from_proposals(ctx, load_proposals(path))
