"""Tier-B alert drafting (SCOPE coverage #19) — the engine half of generate-alerts.

The deterministic scaffolder already emits a log-pattern Alert for a *swallowed publish channel* — the
one error-log it can prove is alert-worthy (a logged-and-dropped failure). But the engine parses every
log statement (`observability.log.statement`, S2), and many error/warn lines are alert-worthy without
being a swallow. *Which* of them warrants paging is an alert-fatigue judgment the engine can't make —
so the `generate-alerts` skill proposes them and the engine re-grounds each on the same non-circular
contract the gap-finder uses:

  locate  — find the proposed log line verbatim in the source; an anchor not present is dropped.
  confirm — there must be a parsed `observability.log.statement` at that line; an `info`/`debug`/`trace`
            line is **refuted** (you don't page on a debug log), an `error`/`warn` line survives.
  render  — the engine, not the LLM, derives the search query from the byte-grounded message literal
            and renders it through the deterministic per-backend adapters (`render_log_pattern`).

Survivors scaffold as `needs-review` `Alert` artifacts, `source_tier=llm`, never auto-verified — the
LLM widened *which* logs get an alert; the engine made every deterministic call (the line exists, the
level is alertable, the query is engine-generated).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.config import load_config
from sre_kb.models.facts import Fact, FactSet
from sre_kb.render.alerts import LogPatternIntent, render_log_pattern, rendered_targets
from sre_kb.scoring.confidence import Signal, confidence
from sre_kb.synth.emit import emit
from sre_kb.tiers import LLM
from sre_kb.util import slug

# Conventional location of the skill's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/alert-proposals.json"

# A log level worth paging on (the survivor set). Everything else is refuted by level — you do not
# raise an alert on an info/debug/trace line, so a proposal pointing at one is dropped deterministically.
_ALERTABLE_LEVELS = {"error", "warn"}
_DEFAULT_SEVERITY = {"error": "high", "warn": "medium"}

_EXT_LANG = {".java": "java"}  # log statements are parsed for Java today (java_spring.log_statements)


@dataclass(frozen=True)
class AlertProposal:
    """One alert-worthiness hypothesis. `anchor` is the verbatim log line, never a line number."""

    anchor: str
    severity: str | None = None
    rationale: str | None = None


@dataclass
class AlertOutcome:
    """Per-proposal audit trail — why a drafted alert was kept or dropped."""

    proposal: AlertProposal
    result: str  # routed | refuted | unconfirmable | unlocatable
    path: str | None = None
    line: int | None = None
    note: str = ""


@dataclass
class AlertDraftResult:
    outcomes: list[AlertOutcome] = field(default_factory=list)
    docs: list[dict] = field(default_factory=list)

    def kept(self) -> list[AlertOutcome]:
        return [o for o in self.outcomes if o.result == "routed"]

    def dropped(self) -> list[AlertOutcome]:
        return [o for o in self.outcomes if o.result != "routed"]


def load_proposals(path: Path) -> list[AlertProposal]:
    """Parse a Copilot-produced proposals file (a bare list or {"proposals": [...]})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("proposals", []) if isinstance(data, dict) else data
    out: list[AlertProposal] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        anchor = str(it.get("anchor") or it.get("excerpt") or "").strip()
        if not anchor:
            continue  # an anchorless proposal can't be grounded
        sev = it.get("severity")
        out.append(AlertProposal(
            anchor=anchor,
            severity=(str(sev).strip().lower() if sev else None),
            rationale=(str(it["rationale"]) if it.get("rationale") else None),
        ))
    return out


def _locate(ctx: ScanContext, anchor: str, globs: tuple[str, ...]) -> tuple[str, int, int] | None:
    """Find `anchor` as a contiguous run of whole source lines: (relpath, start, end) or None."""
    needles = [ln.strip() for ln in anchor.splitlines() if ln.strip()]
    if not needles:
        return None
    for path in ctx.files(*globs):
        rel = ctx.rel(path)
        stripped = [ln.strip() for ln in ctx.read_lines(rel)]
        for i in range(len(stripped) - len(needles) + 1):
            if all(needles[k] == stripped[i + k] for k in range(len(needles))):
                return rel, i + 1, i + len(needles)
    return None


def _log_statement_in(fs: FactSet, rel: str, start: int, end: int) -> Fact | None:
    """The parsed `observability.log.statement` fact whose line falls in [start, end], or None."""
    for f in fs.of("observability.log.statement"):
        if f.evidence.path == rel and start <= f.evidence.lines.start <= end:
            return f
    return None


def _message_literal(ctx: ScanContext, rel: str, line: int) -> str | None:
    """The byte-grounded message literal of the log call at `line` (its first string argument),
    truncated at the first `{}`/`{` placeholder — the stable substring an alert can search for.
    Engine-derived, so the alert query is deterministic, not LLM-supplied. None if no literal."""
    lang = _EXT_LANG.get(Path(rel).suffix)
    if lang is None:
        return None
    module = ctx.module(rel, lang)
    for typedecl in module.types:
        for method in typedecl.methods:
            for call in method.calls:
                if call.line == line and call.str_args:
                    search = call.str_args[0].split("{")[0].strip()
                    return search or None
    return None


def _alert_doc(search: str, severity: str, rationale: str | None, evidence,
               service: str, tools: tuple[str, ...] | None) -> dict:
    """Scaffold a needs-review, Tier-B log-pattern Alert from a grounded error/warn log line."""
    expr = render_log_pattern(LogPatternIntent(search=search, service=service), tools)
    name = slug(f"{service}-{search[:40]}-log-alert")
    spec = {
        "alertType": "threshold",
        "sloRef": None,
        "signalSource": "log-pattern",
        "severity": severity,
        "expr": expr,
        "rationale": ((rationale + " ") if rationale else "")
                     + "Drafted from an error/warn log line (alert-worthiness is a judgment); "
                       "the engine grounded the line and generated the query. Needs review.",
        "class": "cause",
        "signal": {"type": "log", "description": f'error/warn log line "{search}"'},
        "renderTargets": rendered_targets(expr),
    }
    return emit("Alert", name, spec, [evidence], "needs-review", confidence(Signal.INFERRED),
                service, provenance="llm-asserted", unverified_against_live=True)


def reground(ctx: ScanContext, proposals: list[AlertProposal], fs: FactSet,
             service: str, tools: tuple[str, ...] | None = None) -> AlertDraftResult:
    """Locate -> confirm-by-level -> render every proposal. Emits one needs-review Alert per survivor."""
    res = AlertDraftResult()
    globs = tuple(f"*{ext}" for ext in _EXT_LANG)
    for p in proposals:
        loc = _locate(ctx, p.anchor, globs)
        if loc is None:
            res.outcomes.append(AlertOutcome(p, "unlocatable",
                                             note="anchor not found verbatim in the source"))
            continue
        rel, s, e = loc
        stmt = _log_statement_in(fs, rel, s, e)
        if stmt is None:
            res.outcomes.append(AlertOutcome(p, "unconfirmable", rel, s,
                                             note="no parsed log statement at the cited line"))
            continue
        level = str(stmt.attrs.get("level"))
        line = stmt.evidence.lines.start
        if level not in _ALERTABLE_LEVELS:
            res.outcomes.append(AlertOutcome(p, "refuted", rel, line,
                                             note=f"log level '{level}' is not alert-worthy"))
            continue
        search = _message_literal(ctx, rel, line)
        if not search:
            res.outcomes.append(AlertOutcome(p, "unconfirmable", rel, line,
                                             note="no message literal at the log line to alert on"))
            continue
        severity = p.severity or _DEFAULT_SEVERITY.get(level, "medium")
        evidence = ctx.evidence(rel, line, line, "llm.generate_alerts", source_tier=LLM)
        res.docs.append(_alert_doc(search, severity, p.rationale, evidence, service, tools))
        res.outcomes.append(AlertOutcome(p, "routed", rel, line,
                                         note=f"grounded {level} log line — drafted a needs-review alert"))
    return res


def run_generate_alerts(
    target: str, *, proposals_path: str | Path | None = None, service: str | None = None
) -> AlertDraftResult:
    """Scan `target`'s alert proposals and re-ground them. No proposals file -> empty result."""
    root = Path(target).resolve()
    if not root.exists():
        raise FileNotFoundError(f"target not found: {root}")
    ctx = ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)
    path = Path(proposals_path) if proposals_path else (root / PROPOSALS_REL)
    if not path.exists():
        return AlertDraftResult()
    try:
        proposals = load_proposals(path)
    except (json.JSONDecodeError, OSError):
        return AlertDraftResult()  # a malformed proposals file self-gates to "no proposals"
    fs = scan(ctx)
    tools = ((load_config().get("render") or {}).get("alert_tools"))
    return reground(ctx, proposals, fs, service or root.name,
                    tuple(tools) if tools else None)
