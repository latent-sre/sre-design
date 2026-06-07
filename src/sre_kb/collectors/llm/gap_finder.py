"""LLM gap-finder (SPIKE) — the first Tier-B collector.

An LLM (Copilot, running the vendored `assess-resiliency` skill — see
`.github/skills/sre-gap-finder/`) reads the engine's facts + the code and proposes
resiliency *gaps* the AST missed: e.g. a client call site with no timeout. Each proposal
quotes the verbatim excerpt it is pointing at, NOT a line number.

This module is the engine half of the non-circular contract:

  locate  — the engine finds the proposed excerpt in the bytes itself (drops it if the
            quote can't be found verbatim: no fabricated citations).
  stamp   — the engine emits `ctx.evidence(...)` → path:line:excerptHash over the located
            whole lines, so the citation is hash-checkable like any other.
  rederive— the engine independently confirms the gap with the same kind of deterministic
            rule Tier A uses (here: there IS an outbound client call and NO timeout signal
            in scope). A proposal the engine can refute is dropped — the LLM cannot assert
            a gap that isn't there. A proposal with no deterministic basis is dropped too.

Only `confirmed` gaps become facts, each `source_tier="llm"`. Their downstream artifact
(`ResiliencyGap`) is forced to `needs-review`: nothing here auto-verifies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.parsing import parse

# Conventional location of the LLM's output inside the (untrusted) target repo, mirroring
# how resiliency-skills drops its scan output under `.sre-scan/`.
PROPOSALS_REL = ".sre/gap-proposals.json"

_EXT_LANG = {".java": "java", ".cs": "csharp"}
_SOURCE_GLOBS = ("*.java", "*.cs")

# Outbound-client call names — the receiver of a remote dependency call that ought to carry
# a timeout. (Java RestTemplate/WebClient/HttpClient; C# HttpClient.)
_CLIENT_METHODS = {
    "getforobject", "postforobject", "putforobject", "patchforobject", "deleteforobject",
    "getforentity", "postforentity", "exchange", "execute", "retrieve", "bodytomono",
    "getasync", "postasync", "putasync", "deleteasync", "patchasync", "sendasync",
}

# Per-language tokens that evidence a timeout is configured *in scope*. Deliberately narrow:
# a Polly circuit breaker's `TimeSpan.FromSeconds(30)` is NOT a timeout, so `TimeSpan`/
# `Duration` alone are excluded — only timeout-specific tokens count.
_TIMEOUT_TOKENS = {
    "java": (
        "timelimiter", "settimeout", "setconnecttimeout", "setreadtimeout",
        "readtimeout", "connecttimeout", ".timeout(", "requestconfig",
        "httpcomponentsclienthttprequestfactory",
    ),
    "csharp": (
        ".timeout", "timeout =", "timeoutpolicy", "policy.timeout",
        "cancellationtokensource(", ".waitasync(",
    ),
}


@dataclass(frozen=True)
class Proposal:
    """One gap hypothesis from the LLM. `anchor` is excerpt TEXT, never a line number."""

    pattern: str
    anchor: str
    target: str | None = None
    severity: str = "medium"
    rationale: str | None = None


@dataclass
class Outcome:
    """Per-proposal audit trail — the go/no-go evidence for whether the spike is noisy."""

    proposal: Proposal
    result: str  # "confirmed" | "refuted" | "unlocatable" | "unconfirmable" | "unsupported"
    path: str | None = None
    lines: tuple[int, int] | None = None
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
    """Parse a Copilot-produced proposals file. Tolerant of a bare list or {"proposals": [...]}."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("proposals", []) if isinstance(data, dict) else data
    out: list[Proposal] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        anchor = str(it.get("anchor") or it.get("excerpt") or "").strip()
        pattern = str(it.get("pattern") or "").strip().lower()
        if not anchor or not pattern:
            continue  # an unlocatable/typeless proposal can't be grounded
        out.append(Proposal(
            pattern=pattern,
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

def _enclosing_type_text(ctx: ScanContext, rel: str, start: int, end: int):
    """Parse `rel`; return (lang, TypeDecl, MethodDecl|None, type_text) enclosing the cited
    lines, or None if the file can't be parsed for re-derivation."""
    lang = _EXT_LANG.get(Path(rel).suffix)
    if lang is None:
        return None
    module = parse(lang, ctx.read_text(rel))
    enclosing = None
    for t in module.types:
        if t.start <= start and t.end >= end:
            enclosing = t
            break
    if enclosing is None:
        return None
    method = next(
        (m for m in enclosing.methods if m.start <= start and m.end >= end), None
    )
    text = "".join(ctx.read_lines(rel)[enclosing.start - 1 : enclosing.end])
    return lang, enclosing, method, text


def _rederive_timeout(ctx: ScanContext, rel: str, start: int, end: int) -> tuple[str, str]:
    """The engine's independent check for a *timeout* gap, run at the located bytes with the
    same kind of deterministic rule Tier A uses. Returns (verdict, note)."""
    parsed = _enclosing_type_text(ctx, rel, start, end)
    if parsed is None:
        return "unconfirmable", "could not parse an enclosing type at the cited location"
    lang, typedecl, method, type_text = parsed

    # (a) is there actually an outbound client call in scope?
    scope = [method] if method else typedecl.methods
    has_client = any(
        c.method.lower() in _CLIENT_METHODS for m in scope for c in m.calls
    )
    if not has_client:
        return "unconfirmable", "no outbound client call at the cited location to ground a timeout gap"

    # (b) is a timeout configured in scope? annotation, or a timeout-specific token.
    low = type_text.lower()
    ann_has_timeout = bool(method and "@TimeLimiter" in method.annotations)
    token_has_timeout = any(tok in low for tok in _TIMEOUT_TOKENS.get(lang, ()))
    if ann_has_timeout or token_has_timeout:
        return "refuted", "a timeout IS configured in scope — the proposed gap does not hold"
    return "confirmed", "outbound client call with no timeout configured in scope"


_REDERIVERS = {"timeout": _rederive_timeout}


# --------------------------------------------------------------------------- collect

def collect_from_proposals(ctx: ScanContext, proposals: list[Proposal]) -> GapResult:
    """The collector: locate → stamp → re-derive every proposal. Emits one `resiliency.gap`
    Fact per *confirmed* gap; records an Outcome for all (incl. drops) as audit evidence."""
    res = GapResult()
    for p in proposals:
        loc = _locate(ctx, p.anchor)
        if loc is None:
            res.outcomes.append(Outcome(p, "unlocatable", note="anchor not found verbatim in the source"))
            continue
        rel, s, e = loc
        rederive = _REDERIVERS.get(p.pattern)
        if rederive is None:
            # No deterministic confirmation rule for this pattern in the spike → can't assert.
            res.outcomes.append(Outcome(p, "unconfirmable", rel, (s, e),
                                        f"no re-derivation rule for pattern '{p.pattern}'"))
            continue
        verdict, note = rederive(ctx, rel, s, e)
        if verdict != "confirmed":
            res.outcomes.append(Outcome(p, verdict, rel, (s, e), note))
            continue
        target = p.target or Path(rel).stem
        res.facts.append(Fact(
            "resiliency.gap",
            {"pattern": p.pattern, "target": target, "severity": p.severity,
             "rationale": p.rationale, "rederivation": "confirmed", "note": note},
            ctx.evidence(rel, s, e, "llm.gap_finder"),
            Symbol(f"{rel}:{s}-{e}", "gap"),
            source_tier="llm",
        ))
        res.outcomes.append(Outcome(p, "confirmed", rel, (s, e), note))
    return res


def collect(ctx: ScanContext, proposals_path: Path | None = None) -> GapResult:
    """Self-gating entry point: read proposals from `proposals_path` (default the
    conventional in-repo location). No proposals file → empty result."""
    path = proposals_path or (ctx.root / PROPOSALS_REL)
    if not path.exists():
        return GapResult()
    return collect_from_proposals(ctx, load_proposals(path))
