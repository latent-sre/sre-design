"""Tier-B runbook drafting (SCOPE coverage #20) — the engine half of generate-runbooks.

The deterministic scaffolder emits a Runbook only for a swallowed-publish Alert — the one failure mode
it can fully derive. Every other Alert (a burn-rate alert, say) ships with no runbook, and authoring
the diagnosis/remediation prose is a judgment the engine can't make. So the `generate-runbooks` skill
drafts that content and the engine re-grounds it — not the gap-finder's byte-locate contract (runbook
prose isn't a code claim) but the **closed-world reference grounding** the findings narrative uses:

  target   — a drafted runbook must trigger on a real Alert in this run; an `alertRef` that resolves to
             no Alert is dropped, and an Alert that already has a runbook is refuted (no duplicate).
  ground   — every `Kind/name` reference in the drafted prose (symptoms/diagnosis/remediation) must
             resolve to an artifact in this run; references to things that aren't there are named so a
             hallucinated flow/dependency can't hide in a runbook step.

Survivors scaffold as `needs-review`, `source_tier=llm` `Runbook` artifacts carrying the GENERATED
banner, byte-grounded to the same code their target Alert cites. Nothing auto-verifies; the engine
never calls a model — it ingests what Copilot wrote by running the skill.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.reporting.narrative import _REF_RE, allowed_refs
from sre_kb.scoring.confidence import Signal, confidence
from sre_kb.synth.emit import emit
from sre_kb.synth.scaffold import scaffold
from sre_kb.tiers import LLM

# Conventional location of the skill's output inside the (untrusted) target repo.
PROPOSALS_REL = ".sre/runbook-proposals.json"


@dataclass(frozen=True)
class RunbookProposal:
    """One drafted runbook. `alert_ref` names the Alert it triggers on (must be a real run Alert)."""

    alert_ref: str
    symptoms: tuple[str, ...] = ()
    diagnosis: tuple[str, ...] = ()
    remediation: tuple[str, ...] = ()
    escalation: str | None = None
    related_flow: str | None = None


@dataclass
class RunbookOutcome:
    """Per-proposal audit trail — why a drafted runbook was kept or dropped."""

    proposal: RunbookProposal
    result: str  # routed | refuted | ungrounded-target
    ungrounded_refs: tuple[str, ...] = ()
    note: str = ""


@dataclass
class RunbookDraftResult:
    outcomes: list[RunbookOutcome] = field(default_factory=list)
    docs: list[dict] = field(default_factory=list)

    def kept(self) -> list[RunbookOutcome]:
        return [o for o in self.outcomes if o.result == "routed"]

    def dropped(self) -> list[RunbookOutcome]:
        return [o for o in self.outcomes if o.result != "routed"]


def _strs(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v).strip() for v in value if str(v).strip())


def load_proposals(path: Path) -> list[RunbookProposal]:
    """Parse a Copilot-produced proposals file (a bare list or {"proposals": [...]})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("proposals", []) if isinstance(data, dict) else data
    out: list[RunbookProposal] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        alert_ref = str(it.get("alertRef") or it.get("alert_ref") or "").strip()
        if not alert_ref:
            continue  # a runbook with no Alert to trigger on can't be grounded
        out.append(RunbookProposal(
            alert_ref=alert_ref,
            symptoms=_strs(it.get("symptoms")),
            diagnosis=_strs(it.get("diagnosis")),
            remediation=_strs(it.get("remediation")),
            escalation=(str(it["escalation"]).strip() if it.get("escalation") else None),
            related_flow=(str(it["relatedFlow"]).strip() if it.get("relatedFlow") else None),
        ))
    return out


def _runbooked_alerts(docs: list[dict]) -> set[str]:
    """Alert names that already have a Runbook (its trigger.alertRef), so we never duplicate one."""
    return {(d["spec"].get("trigger") or {}).get("alertRef")
            for d in docs if d["kind"] == "Runbook"} - {None}


def _ungrounded_refs(texts: list[str], allowed: set[str], known_kinds: set[str]) -> set[str]:
    """Every `Kind/name` citation in `texts` whose Kind is real but which isn't a run artifact."""
    unknown: set[str] = set()
    for text in texts:
        for kind, name in _REF_RE.findall(text):
            if kind in known_kinds and f"{kind}/{name}" not in allowed:
                unknown.add(f"{kind}/{name}")
    return unknown


def _evidence_for(ctx: ScanContext, alert_doc: dict):
    """Rebuild a Tier-B citation over the same bytes the target Alert cites — so the drafted runbook
    is byte-grounded to the code its alert is about, stamped source_tier=llm."""
    ev = (alert_doc.get("evidence") or [{}])[0]
    lines = ev.get("lines") or {}
    path, start = ev.get("path"), lines.get("start", 1)
    end = lines.get("end", start)
    return ctx.evidence(path, start, end, "llm.generate_runbooks", source_tier=LLM)


def reground(ctx: ScanContext, proposals: list[RunbookProposal], docs: list[dict],
             service: str) -> RunbookDraftResult:
    """Target-resolve -> closed-world ground -> draft every proposal."""
    alert_docs = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Alert"}
    flow_names = {d["metadata"]["name"] for d in docs if d["kind"] == "Flow"}
    # Drafted refs join the covered set as we go, so two proposals for the same Alert can't emit two
    # same-named runbooks — the second is refused like an already-covered one.
    covered = _runbooked_alerts(docs)
    allowed = allowed_refs([], docs)
    known_kinds = {d.get("kind") for d in docs}
    res = RunbookDraftResult()
    for p in proposals:
        if p.alert_ref not in alert_docs:
            res.outcomes.append(RunbookOutcome(p, "ungrounded-target",
                note=f"alertRef '{p.alert_ref}' resolves to no Alert in this run"))
            continue
        if p.alert_ref in covered:
            res.outcomes.append(RunbookOutcome(p, "refuted",
                note=f"Alert '{p.alert_ref}' already has a runbook"))
            continue
        related = p.related_flow if p.related_flow in flow_names else None
        prose = list(p.symptoms) + list(p.diagnosis) + list(p.remediation)
        unknown = _ungrounded_refs(prose, allowed, known_kinds)
        spec = {
            "banner": "GENERATED — verify before executing",
            "trigger": {"alertRef": p.alert_ref},
            "symptoms": list(p.symptoms),
            "diagnosis": [{"step": s} for s in p.diagnosis],
            "remediation": list(p.remediation),
            "escalation": (p.escalation or "service owner (needs-review)"),
        }
        if related:
            spec["relatedFlow"] = related
        cross = [{"kind": "Alert", "name": p.alert_ref, "relation": "covers"}]
        if related:
            cross.append({"kind": "Flow", "name": related, "relation": "covers"})
        res.docs.append(emit("Runbook", p.alert_ref, spec, [_evidence_for(ctx, alert_docs[p.alert_ref])],
                             "needs-review", confidence(Signal.INFERRED), service,
                             cross_refs=cross, provenance="llm-asserted", unverified_against_live=True))
        covered.add(p.alert_ref)
        note = ("drafted a needs-review runbook" if not unknown
                else f"drafted; {len(unknown)} ungrounded reference(s) flagged")
        res.outcomes.append(RunbookOutcome(p, "routed", tuple(sorted(unknown)), note))
    return res


def run_generate_runbooks(
    target: str, *, proposals_path: str | Path | None = None, service: str | None = None
) -> RunbookDraftResult:
    """Scan + scaffold `target`, then re-ground its runbook proposals. No file -> empty result."""
    root = Path(target).resolve()
    if not root.exists():
        raise FileNotFoundError(f"target not found: {root}")
    ctx = ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)
    path = Path(proposals_path) if proposals_path else (root / PROPOSALS_REL)
    if not path.exists():
        return RunbookDraftResult()
    try:
        proposals = load_proposals(path)
    except (json.JSONDecodeError, OSError):
        return RunbookDraftResult()  # a malformed proposals file self-gates to "no proposals"
    docs = scaffold(scan(ctx), ctx)
    return reground(ctx, proposals, docs, service or root.name)
