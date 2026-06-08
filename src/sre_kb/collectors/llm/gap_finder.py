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
import re
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.signatures import fires
from sre_kb.taxonomy import severity_rank
from sre_kb.tiers import AST, LLM

# Conventional location of the LLM's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/gap-proposals.json"

_EXT_LANG = {".java": "java", ".cs": "csharp", ".py": "python"}
_SOURCE_GLOBS = ("*.java", "*.cs", "*.py")
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

# Gap category -> the resilience concern(s) whose PRESENCE in scope refutes the gap (the absence
# doesn't hold). Re-derivation fires the *shared* signatures for these, so it can't drift from
# Tier-A detection. Categories absent here are recorded but not asserted (no probe yet → can't
# ground). Annotation keys that carry a resilience instance name, used to scope config probing.
_REFUTING_CONCERNS = {
    "missing-timeout": ("timeout",),
    "unguarded-critical-dependency": ("circuit-breaker", "fallback", "timeout"),
}
_INSTANCE_ANNOTATIONS = ("@CircuitBreaker", "@TimeLimiter", "@Retry", "@Bulkhead", "@RateLimiter")

# CONFIRMATION-probe categories (opposite polarity to _REFUTING_CONCERNS, §9.4): a gap survives
# only if the deterministic rule FIRES at the LLM's pointer — at which point the engine has
# re-derived the fact itself, so it GRADUATES to Tier-A (source_tier=ast) and can reach `verified`.
# Two flavours: `swallowed-failure` reads the AST swallow detector (`Call.swallow`); the rest fire a
# shared signature at the pointer's enclosing type. Both surface things the collectors don't emit
# facts for today (swallows outside messaging egress; scheduled jobs at all), which is the recall.
_CONFIRMING_CATEGORIES = {"swallowed-failure", "undocumented-job"}
_CONFIRMING_SIGNATURE = {"undocumented-job": "scheduled"}

# Judgment-call categories (§7.9): no deterministic probe can ground these — "is this a data-loss
# path / a non-idempotent retry / an unbounded resource?" is a reasoning call. We still GROUND the
# citation (the anchor must locate), then surface them as Tier-B `needs-review` candidates routed to
# the human/Copilot oracle — never auto-verified, and subject to the same noise budget. This is the
# honest home for the categories the engine cannot re-derive.
_JUDGMENT_CATEGORIES = {"data-loss-path", "missing-idempotency", "unbounded-resource",
                        "missing-backpressure", "missing-load-shedding"}

# A judgment call can't be CONFIRMED by a probe, but if its mechanism is already PRESENT in scope the
# gap plainly doesn't hold — these categories refute (drop, never reaching the oracle) when the shared
# signature fires at the cited location. Only categories with a deterministic positive signature
# appear here; the refute reads the same `signatures` library Tier-A keys off, so it can't drift
# (HYBRID-PLAN §7.4/§9.4). The load-shed/backpressure vocab (N5) is the first to use this seam.
_JUDGMENT_REFUTERS = {"missing-backpressure": "backpressure", "missing-load-shedding": "load-shed"}


def gap_categories() -> set[str]:
    """Every known gap category the gap-finder can emit (refutation + confirmation + judgment).
    Used by the graduation loop to validate a reviewer's `confirm-gap` verdict."""
    return set(_REFUTING_CONCERNS) | set(_CONFIRMING_CATEGORIES) | set(_JUDGMENT_CATEGORIES)


def target_concerns(category: str) -> tuple[str, ...]:
    """The deterministic concern(s) a confirmed `category` would graduate into a signature for — the
    shared-signature concerns Tier-A keys off. Empty for `swallowed-failure` (graduates via the AST
    swallow detector, not a regex) and for judgment categories (no deterministic rule grounds them)."""
    if category in _REFUTING_CONCERNS:
        return _REFUTING_CONCERNS[category]
    if category in _CONFIRMING_SIGNATURE:
        return (_CONFIRMING_SIGNATURE[category],)
    return ()


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

    def kept(self) -> list[Outcome]:
        """Survivors that became facts — engine-`confirmed` plus judgment-`routed`."""
        return [o for o in self.outcomes if o.result in ("confirmed", "routed")]

    def dropped(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.result not in ("confirmed", "routed")]


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
    module = ctx.module(rel, lang)
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


def _scope_names(method, target: str | None) -> set[str]:
    """The resilience *instance* names that identify this dependency in config — the breaker/
    limiter `name=` on the enclosing method, plus the proposed target. Used to scope the config
    probe: a timeout block for some *other* client must not refute this gap."""
    names: set[str] = set()
    if method:
        for ann in _INSTANCE_ANNOTATIONS:
            args = method.annotations.get(ann)
            if args and args.get("name"):
                names.add(args["name"].lower())
    if target:
        names.add(target.lower())
    return {n for n in names if n}


def _name_in_text(name: str, text: str) -> bool:
    """Whole-token match for a resilience *instance* name in config text. `payments` matches
    `…instances.payments.timeout…` but NOT `payments-api`, a *different* instance it is merely a
    prefix of — instance names are delimited by non-`[\\w-]` (path separators, quotes, whitespace),
    so a prefix substring must not scope-match a longer token (HYBRID-PLAN §9.5 ⑤). Without this a
    timeout block for `payments-api` would wrongly refute a real gap on `payments`."""
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I) is not None


def _rederive(ctx: ScanContext, rel: str, start: int, end: int, category: str, target: str | None):
    """Deterministic refutation probe for `category` at the cited bytes, using the shared
    `signatures` library. Any refuting concern firing in scope drops the gap. Returns
    (verdict, checked, note)."""
    refuters = _REFUTING_CONCERNS[category]
    parsed = _enclosing_type(ctx, rel, start, end)
    if parsed is None:
        return "unconfirmable", (rel,), "could not parse an enclosing type at the cited location"
    typedecl, method, type_text = parsed
    if not _has_client_call(typedecl, method):
        return "unconfirmable", (rel,), "no outbound client call at the cited location to ground the gap"

    # (a) code scope: a signature in the enclosing type refutes the absence.
    checked = [rel]
    for concern in refuters:
        if fires(concern, type_text):
            return "refuted", (rel,), f"the {concern} signature fires in scope — the gap does not hold"

    # (b) config scope, TARGET-SCOPED: only a config block that names this dependency's resilience
    # instance can refute it — a timeout for some other client in the same file must not.
    names = _scope_names(method, target)
    for cpath, ctext in _config_texts(ctx):
        checked.append(cpath)
        if names and not any(_name_in_text(n, ctext) for n in names):
            continue  # this config doesn't name this instance (whole-token) — out of scope
        for concern in refuters:
            if fires(concern, ctext):
                return ("refuted", tuple(checked),
                        f"the {concern} signature fires for this instance in {cpath} — the gap does not hold")
    return "confirmed", tuple(checked), f"no refuting signature {list(refuters)} fires in {len(checked)} checked location(s)"


def _confirm_swallow(ctx: ScanContext, rel: str, start: int, end: int):
    """Confirmation probe: run the deterministic swallow detector at the cited pointer. Returns the
    `Swallow` (catch span + log call) if a logged-and-swallowed failure sits at the pointer, else
    None. Detection already exists per-Call in the AST model; we just read it at the located range
    — for ANY call type, which is the recall the messaging-only collectors miss (§9.4)."""
    parsed = _enclosing_type(ctx, rel, start, end)
    if parsed is None:
        return None
    typedecl, method, _ = parsed
    for m in ([method] if method else typedecl.methods):
        for c in m.calls:
            if start <= c.line <= end and c.swallow is not None:
                return c.swallow
    return None


def _confirm(ctx: ScanContext, rel: str, start: int, end: int, category: str):
    """Dispatch a confirmation probe. Returns ((evid_start, evid_end), note) if the deterministic
    rule fires at the pointer (→ graduate to Tier-A), or (None, why) if it doesn't (→ drop)."""
    if category == "swallowed-failure":
        sw = _confirm_swallow(ctx, rel, start, end)
        if sw is None:
            return None, "no logged-and-swallowed failure at the cited pointer"
        return (sw.start, sw.end), f"swallow rule fired at the pointer (catch logs '{sw.log_method}', no rethrow)"
    # Signature-based confirmation (e.g. undocumented-job → the `scheduled` signature).
    concern = _CONFIRMING_SIGNATURE[category]
    parsed = _enclosing_type(ctx, rel, start, end)
    if parsed is None:
        return None, "could not parse an enclosing type at the cited location"
    _, _, type_text = parsed
    if fires(concern, type_text):
        return (start, end), f"the {concern} signature fires at the pointer — engine-confirmed"
    return None, f"the {concern} signature does not fire at the pointer"


# --------------------------------------------------------------------------- collect

def collect_from_proposals(
    ctx: ScanContext, proposals: list[Proposal], *, max_candidates: int | None = None
) -> GapResult:
    """The collector: locate → stamp → re-derive every proposal. Emits one `resiliency.gap` Fact
    per surviving gap; records an Outcome for all (incl. drops) as audit evidence. A noise budget
    (§7.9) ranks survivors by severity and keeps at most `max_candidates` — the rest are recorded
    `capped` so a cry-wolf run can't flood a reviewer."""
    res = GapResult()
    survivors: list[tuple[Outcome, Fact]] = []
    for p in proposals:
        loc = _locate(ctx, p.anchor)
        if loc is None:
            res.outcomes.append(Outcome(p, "unlocatable", note="anchor not found verbatim in the source"))
            continue
        rel, s, e = loc

        # Confirmation probe (§9.4): the rule firing at the pointer confirms the gap AND graduates
        # it to Tier-A — the engine re-derived it, so it is no longer LLM-asserted. Never noise-capped
        # (it is a confirmed engine finding, not a candidate). A pointer where the rule doesn't fire
        # is dropped (the LLM can't assert a swallow the engine can't reproduce).
        if p.category in _CONFIRMING_CATEGORIES:
            span, note = _confirm(ctx, rel, s, e, p.category)
            if span is None:
                res.outcomes.append(Outcome(p, "refuted", rel, (s, e), (rel,), note))
                continue
            target = p.target or Path(rel).stem
            res.facts.append(Fact(
                "resiliency.gap",
                {"category": p.category, "target": target, "severity": p.severity,
                 "rationale": p.rationale, "rederivation": "confirmed", "checked": [rel], "note": note},
                ctx.evidence(rel, span[0], span[1], f"gap_finder.{p.category}", source_tier=AST),
                Symbol(f"{rel}:{span[0]}-{span[1]}", "gap"),
            ))
            res.outcomes.append(Outcome(p, "confirmed", rel, span, (rel,),
                                        "graduated to Tier-A — engine re-derived the gap at the pointer"))
            continue

        if p.category in _JUDGMENT_CATEGORIES:
            # No probe can CONFIRM a judgment call (does this path *need* backpressure? a reasoning
            # call) — so it grounds the citation and routes to the oracle as needs-review. But if the
            # category has a positive signature and that mechanism already fires in scope, the gap
            # doesn't hold — refute it rather than spend the oracle's attention on it.
            refuter = _JUDGMENT_REFUTERS.get(p.category)
            if refuter:
                parsed = _enclosing_type(ctx, rel, s, e)
                if parsed is not None and fires(refuter, parsed[2]):
                    res.outcomes.append(Outcome(p, "refuted", rel, (s, e), (rel,),
                                                f"the {refuter} signature fires in scope — the gap does not hold"))
                    continue
            # No deterministic probe — locate-grounded only, routed to the oracle as needs-review.
            target = p.target or Path(rel).stem
            fact = Fact(
                "resiliency.gap",
                {"category": p.category, "target": target, "severity": p.severity,
                 "rationale": p.rationale, "rederivation": "judgment", "checked": [rel],
                 "note": "judgment call — no deterministic probe; routed to human/oracle review"},
                ctx.evidence(rel, s, e, "llm.gap_finder", source_tier=LLM),
                Symbol(f"{rel}:{s}-{e}", "gap"),
            )
            survivors.append((Outcome(p, "routed", rel, (s, e), (rel,),
                                      "judgment call — routed to human/oracle review"), fact))
            continue

        if p.category not in _REFUTING_CONCERNS:
            res.outcomes.append(Outcome(p, "unconfirmable", rel, (s, e),
                                        note=f"no deterministic probe for category '{p.category}'"))
            continue
        verdict, checked, note = _rederive(ctx, rel, s, e, p.category, p.target)
        if verdict != "confirmed":
            res.outcomes.append(Outcome(p, verdict, rel, (s, e), checked, note))
            continue
        target = p.target or Path(rel).stem
        fact = Fact(
            "resiliency.gap",
            {"category": p.category, "target": target, "severity": p.severity,
             "rationale": p.rationale, "rederivation": "confirmed", "checked": list(checked), "note": note},
            ctx.evidence(rel, s, e, "llm.gap_finder", source_tier=LLM),
            Symbol(f"{rel}:{s}-{e}", "gap"),
        )
        survivors.append((Outcome(p, "confirmed", rel, (s, e), checked, note), fact))

    # Noise budget: highest severity first (stable within a severity), cap the rest.
    survivors.sort(key=lambda of: severity_rank(of[0].proposal.severity))
    for i, (outcome, fact) in enumerate(survivors):
        if max_candidates is not None and i >= max_candidates:
            outcome.result = "capped"
            outcome.note = f"dropped by noise budget (max_candidates={max_candidates})"
            res.outcomes.append(outcome)
        else:
            res.facts.append(fact)
            res.outcomes.append(outcome)
    return res


def collect(
    ctx: ScanContext, proposals_path: Path | None = None, *, max_candidates: int | None = None
) -> GapResult:
    """Self-gating entry point: read proposals from `proposals_path` (default the conventional
    in-repo location). No proposals file → empty result."""
    path = proposals_path or (ctx.root / PROPOSALS_REL)
    if not path.exists():
        return GapResult()
    return collect_from_proposals(ctx, load_proposals(path), max_candidates=max_candidates)
