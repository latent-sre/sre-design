"""LLM-authored findings narrative (HYBRID-PLAN §9.7 N5) — advisory, Tier-B.

The `findings` digest is deterministic and trusted; this adds the "so what / what to do" prose an
on-call reviewer wants, authored by Copilot. It is the gap-finder contract pointed the other way: the
engine doesn't *consume* an LLM claim here, it *bounds* an LLM's prose against its own facts.

  brief    — the engine emits a closed-world brief: the ranked findings plus the exact set of artifact
             references the narrative is allowed to mention. The LLM summarizes ONLY this.
  ground   — the engine validates the returned prose: every artifact-ref-shaped citation (`Kind/name`)
             whose Kind is a real artifact kind must resolve to an artifact in this run. A reference to
             something that isn't there is flagged ungrounded — a hallucinated risk can't masquerade as
             a finding. Counts/severities in the prose are advisory and not machine-checked.

The narrative never gates and never auto-verifies: it is always rendered as a `needs-review`, source-
LLM advisory block. The engine never calls a model — it emits the brief and ingests what Copilot wrote
(the same out-of-process seam as the gap-finder and the challenge oracle).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Conventional in-repo location for Copilot's authored narrative (parallel to gap-proposals.json).
NARRATIVE_REL = ".sre/findings-narrative.md"

# An artifact reference as it appears in prose: a CamelCase Kind, a slash, a slug-ish name. Only
# treated as a citation when the Kind is a real artifact kind, so prose like "TCP/IP" or "and/or" is
# left alone.
# The name may contain internal ./-/_ but must start and end alphanumeric, so trailing sentence
# punctuation ("Flow/create-order.") isn't glued onto the name.
_REF_RE = re.compile(r"\b([A-Z][A-Za-z0-9]+)/([A-Za-z0-9](?:[\w.-]*[A-Za-z0-9])?)")


@dataclass
class NarrativeCheck:
    """The grounding verdict on an LLM narrative — advisory either way, but ungrounded refs are named."""

    grounded: bool
    cited_refs: list[str]    # recognized artifact refs the narrative cites that exist in this run
    unknown_refs: list[str]  # recognized-kind refs that DON'T exist in this run (treat as suspect)
    note: str


def _ref(doc: dict) -> str | None:
    kind, name = doc.get("kind"), (doc.get("metadata") or {}).get("name")
    return f"{kind}/{name}" if kind and name else None


def allowed_refs(findings: list[dict], docs: list[dict]) -> set[str]:
    """Every artifact reference the narrative may mention: each artifact in the run, plus each
    finding's artifact (a closed world — anything outside it is ungrounded)."""
    refs = {r for d in docs if (r := _ref(d))}
    refs |= {f["artifact"] for f in findings if f.get("artifact")}
    return refs


def narrative_brief(service: str, run_id: str, findings: list[dict], docs: list[dict]) -> dict:
    """The deterministic brief handed to Copilot: the ranked findings and the closed set of artifact
    references it may cite. Summarizing this — and only this — keeps the narrative grounded."""
    highs = sum(1 for f in findings if f["severity"] in ("critical", "high"))
    meds = sum(1 for f in findings if f["severity"] == "medium")
    by_type: dict[str, int] = {}
    for f in findings:
        by_type[f["type"]] = by_type.get(f["type"], 0) + 1
    return {
        "service": service,
        "runId": run_id,
        "instruction": (
            "Write a brief SRE narrative over these findings — the 'so what' and what to do next. "
            "Reference ONLY artifacts listed in allowedRefs (as `Kind/name`); do not invent risks, "
            "artifacts, or severities. This narrative is advisory (Tier-B) and lands needs-review."
        ),
        "summary": {"findings": len(findings), "high": highs, "medium": meds, "byType": by_type},
        "findings": [
            {k: f.get(k) for k in ("severity", "type", "title", "detail", "artifact",
                                   "impactedFlows", "evidence")}
            for f in findings
        ],
        "allowedRefs": sorted(allowed_refs(findings, docs)),
    }


def validate_narrative(text: str, findings: list[dict], docs: list[dict]) -> NarrativeCheck:
    """Ground an LLM narrative against the digest: every `Kind/name` citation whose Kind is a real
    artifact kind must resolve to an artifact in this run; any that doesn't is ungrounded."""
    allowed = allowed_refs(findings, docs)
    known_kinds = {d.get("kind") for d in docs} | {a.split("/", 1)[0] for a in allowed}
    cited: set[str] = set()
    unknown: set[str] = set()
    for kind, name in _REF_RE.findall(text):
        if kind not in known_kinds:
            continue  # not an artifact citation (ordinary prose with a slash)
        ref = f"{kind}/{name}"
        (cited if ref in allowed else unknown).add(ref)
    grounded = not unknown
    note = (
        "all artifact references resolve to this run's findings" if grounded
        else f"{len(unknown)} reference(s) not in this run: " + ", ".join(sorted(unknown))
    )
    return NarrativeCheck(grounded, sorted(cited), sorted(unknown), note)


def render_narrative(service: str, text: str, check: NarrativeCheck) -> str:
    """Frame the validated narrative as a Tier-B advisory block — labeled needs-review / source LLM,
    with any ungrounded references called out. Never gates."""
    out = [
        f"## SRE narrative — {service} (advisory · needs-review · source: LLM)",
        "",
        text.strip(),
        "",
        "> ⚠️ **Tier-B advisory.** LLM-authored over the engine's findings digest; not verified.",
    ]
    if check.unknown_refs:
        out.append(
            "> **Ungrounded references** (not in this run's artifacts — treat as suspect): "
            + ", ".join(f"`{r}`" for r in check.unknown_refs)
        )
    return "\n".join(out) + "\n"
