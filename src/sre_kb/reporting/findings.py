"""Findings digest: aggregate the cross-cutting SRE risks the engine already computes
(scattered across BlastRadius artifacts) into one ranked, evidence-linked summary — the
"so what" for an on-call reviewer."""

from __future__ import annotations

from sre_kb.tiers import artifact_tier, tier_label

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_TYPE_RANK = {"data-loss-risk": 0, "uncontained-critical-dep": 1, "broad-impact-dependency": 2}


def _first_evidence(doc: dict) -> str | None:
    ev = (doc.get("evidence") or [{}])[0]
    if not ev.get("path"):
        return None
    lines = ev.get("lines") or {}
    start, end = lines.get("start"), lines.get("end")
    if start is None or end is None:
        return ev["path"]  # no line range -> just the path, not "path:None-None"
    return f"{ev['path']}:{start}-{end}"


def collect_findings(docs: list[dict]) -> list[dict]:
    """Extract ranked risk findings from BlastRadius artifacts (severity-ordered), plus the
    cf-env snapshot adoption nudges (§4.3)."""
    out: list[dict] = []
    for d in docs:
        if d.get("kind") != "BlastRadius":
            continue
        spec = d.get("spec", {})
        node = spec.get("node") or {}
        ref = f"{d['kind']}/{d['metadata']['name']}"
        common = {
            "severity": spec.get("severityHint", "low"),
            "impactedFlows": spec.get("impactedFlows") or [],
            "artifact": ref,
            "evidence": _first_evidence(d),
            "tier": artifact_tier(d),
        }
        if (spec.get("stateful") or {}).get("dataLossRisk"):
            out.append({
                "type": "data-loss-risk",
                "title": f"{node.get('name')} can lose data on failure",
                "detail": "A failure here is logged and swallowed; in-flight data is lost with no replay.",
                **common,
            })
        elif spec.get("dependencyCriticality") == "critical" and not spec.get("containment"):
            out.append({
                "type": "uncontained-critical-dep",
                "title": f"{node.get('name')} is a critical dependency with no containment",
                "detail": "No circuit breaker or fallback; a failure propagates straight to the caller.",
                **common,
            })
        elif spec.get("severityHint") == "high" and spec.get("containment"):
            out.append({
                "type": "broad-impact-dependency",
                "title": f"{node.get('name')} is shared across many flows",
                "detail": "A failure degrades several flows at once even though it is behind a bulkhead.",
                **common,
            })
    out += _snapshot_findings(docs)
    out.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 9), _TYPE_RANK.get(f["type"], 9), f["title"]))
    return out


def _snapshot_findings(docs: list[dict]) -> list[dict]:
    """§4.3 adoption loop: a PCF app with no checked-in cf-env snapshot — or a stale one — is
    itself a finding, so the convention propagates instead of relying on someone remembering.
    Deterministic from the docs: Deployment proves the app is on PCF, a populated
    Topology.pcfSpaces proves a snapshot was ingested, Dependency.snapshot.capturedAt carries
    its age."""
    from datetime import UTC, datetime

    from sre_kb.config import load_config

    pcf = next((d for d in docs if d.get("kind") == "Deployment"
                and (d.get("spec") or {}).get("hosting") == "PCF"), None)
    if pcf is None:
        return []
    common = {"severity": "info", "impactedFlows": [],
              "artifact": f"Deployment/{pcf['metadata']['name']}",
              "evidence": _first_evidence(pcf), "tier": "ast"}
    has_snapshot = any(d.get("kind") == "Topology" and (d.get("spec") or {}).get("pcfSpaces")
                       for d in docs)
    if not has_snapshot:
        return [{
            "type": "missing-cf-env-snapshot",
            "title": "no cf-env snapshot is checked in",
            "detail": ("A credential-stripped .sre/cf-env.json (from `cf env <app>`) would type "
                       "the service bindings, populate org/space, and group estate drawings — "
                       "see the cf-env snapshot convention (NEXT-INCREMENTS §4.3)."),
            **common,
        }]
    max_age = int((load_config().get("estate") or {}).get("snapshot_max_age_days", 90))
    stamps = []
    for d in docs:
        if d.get("kind") != "Dependency":
            continue
        captured = ((d.get("spec") or {}).get("snapshot") or {}).get("capturedAt")
        if not captured:
            continue
        try:
            ts = datetime.fromisoformat(str(captured))
        except ValueError:
            continue
        stamps.append(ts if ts.tzinfo else ts.replace(tzinfo=UTC))
    if not stamps:
        return []
    age_days = (datetime.now(UTC) - min(stamps)).days
    if age_days <= max_age:
        return []
    return [{
        "type": "stale-cf-env-snapshot",
        "title": f"the cf-env snapshot is {age_days} day(s) old",
        "detail": (f"Snapshot-derived facts drift from live platform state; this one exceeds "
                   f"the {max_age}-day freshness budget (estate.snapshot_max_age_days) — "
                   "re-run `cf env <app>`, redact, and refresh .sre/cf-env.json."),
        **common,
    }]


# --- §7.1 tier-conflict detector ------------------------------------------------------
#
# When Tier-A (AST) and Tier-B (LLM) disagree about the same (concern, target) — the AST has a
# circuit breaker the LLM flags as missing, or vice versa — emit a `tier-conflict` rather than
# silently dropping the Tier-B signal. It's a near-zero-cost detector for Tier-A extraction bugs
# (a Tier-A false positive caught by the LLM) and Tier-B false positives. Dormant until a Tier-B
# collector exists; activates in Phase 4. AST emits presence facts; a Tier-B gap fact (`gap.*`)
# asserts a pattern is *absent*, which is what makes a static disagreement detectable.

_PRESENCE_CONCERN = {"resiliency.circuitbreaker": "circuit-breaker", "resiliency.fallback": "fallback"}

# The REAL Tier-B absence facts are `resiliency.gap` (the Phase-4 gap-finder); a category asserts
# the absence of the concern(s) it probes for. Only categories overlapping the Tier-A presence
# vocabulary above can produce a detectable disagreement. (The `gap.<concern>` shape predates the
# gap-finder and is kept for compatibility, but nothing in the engine emits it.)
_GAP_CATEGORY_CONCERNS = {"unguarded-critical-dependency": ("circuit-breaker", "fallback")}


def _conflict_target(fact) -> str | None:
    a = fact.attrs
    return a.get("targetSymbol") or a.get("forTarget") or a.get("target") or a.get("name")


def detect_tier_conflicts(facts: list) -> list[dict]:
    """Flag (concern, target) pairs where Tier-A and Tier-B assert opposite presence."""
    claims: dict[tuple[str, str], dict[str, set[bool]]] = {}

    def record(f, concern: str, present: bool) -> None:
        target = _conflict_target(f)
        if not target:
            return
        tier = getattr(f.evidence, "source_tier", "ast")
        claims.setdefault((concern, target), {}).setdefault(tier, set()).add(present)

    for f in facts:
        if (concern := _PRESENCE_CONCERN.get(f.type)) is not None:
            record(f, concern, True)
        elif f.type == "resiliency.gap":
            for concern in _GAP_CATEGORY_CONCERNS.get(f.attrs.get("category"), ()):
                record(f, concern, False)
        elif f.type.startswith("gap."):
            record(f, f.attrs.get("concern") or f.type.split(".", 1)[1], False)

    conflicts: list[dict] = []
    for (concern, target), by_tier in sorted(claims.items()):
        ast, llm = by_tier.get("ast", set()), by_tier.get("llm", set())
        if ast and llm and ast != llm:
            conflicts.append({
                "type": "tier-conflict",
                "concern": concern,
                "target": target,
                "astPresent": True in ast,
                "llmPresent": True in llm,
                "detail": (
                    f"Tier-A {'has' if True in ast else 'lacks'} and Tier-B "
                    f"{'has' if True in llm else 'lacks'} {concern} for {target} — "
                    f"reconcile (a Tier-A extraction bug or a Tier-B false positive)."
                ),
            })
    return conflicts


# --- §3.3 graduation flywheel: the stats trigger -------------------------------------
#
# The tracker tallies reviewer confirmations and graduation-draft turns a promotion-ready
# category into a signature sketch — but nothing *announced* readiness; a maintainer had to
# remember to run `graduation-candidates`. This finding closes that gap: crossing the
# threshold surfaces automatically wherever findings are read, and the AI surface shrinks by
# one category when it's acted on.

def graduation_findings(target_root, threshold: int) -> list[dict]:
    """One `graduation-ready` finding per promotion-ready category in the target repo's
    graduation tracker (confirmed >= threshold, zero false positives, not yet promoted)."""
    from pathlib import Path

    from sre_kb.graduation import TRACKER_REL, GraduationTracker

    return [{
        "type": "graduation-ready",
        "severity": "info",
        "title": f"gap category '{cat.category}' is ready to graduate to Tier-A",
        "detail": (f"{cat.confirmed} reviewer confirmation(s), zero false positives — run "
                   "`sre-kb graduation-candidates` for the deterministic signature sketch and "
                   "merge it by hand; the LLM stops being asked about this category."),
        "impactedFlows": [],
        "artifact": f"GraduationTracker/{cat.category}",
        "evidence": TRACKER_REL,
        "tier": "ast",
    } for cat in GraduationTracker.load(Path(target_root)).candidates(threshold)]


def _counts(docs: list[dict]) -> dict[str, int]:
    by: dict[str, int] = {}
    for d in docs:
        by[d.get("status", "?")] = by.get(d.get("status", "?"), 0) + 1
    return by


def _tally(findings: list[dict]) -> tuple[int, int]:
    # "critical" (e.g. shared-datastore co-tenancy) counts as high-or-above, not dropped.
    return (
        sum(1 for f in findings if f["severity"] in ("critical", "high")),
        sum(1 for f in findings if f["severity"] == "medium"),
    )


def render_text(service: str, run_id: str, findings: list[dict], docs: list[dict]) -> str:
    lines = [f"SRE findings — {service} (run {run_id})", ""]
    if not findings:
        lines.append("No high/medium-risk findings. ✓")
    for f in findings:
        lines.append(f"[{f['severity'].upper()}] {f['type']} ({tier_label(f.get('tier', 'ast'))}): {f['title']}")
        lines.append(f"    {f['detail']}")
        meta = []
        if f["impactedFlows"]:
            meta.append("flows: " + ", ".join(f["impactedFlows"]))
        if f["evidence"]:
            meta.append("evidence: " + f["evidence"])
        if meta:
            lines.append("    " + "   ".join(meta))
        lines.append(f"    → {f['artifact']}")
        lines.append("")
    highs, meds = _tally(findings)
    by = _counts(docs)
    lines.append(
        f"{len(findings)} finding(s): {highs} high, {meds} medium.  "
        f"Artifacts: " + ", ".join(f"{k} {by[k]}" for k in sorted(by))
    )
    return "\n".join(lines) + "\n"


def render_md(service: str, run_id: str, findings: list[dict], docs: list[dict]) -> str:
    highs, meds = _tally(findings)
    out = [f"# SRE findings — {service}", "", f"_{len(findings)} finding(s): {highs} high, {meds} medium._", ""]
    if not findings:
        out.append("No high/medium-risk findings. ✓")
    for f in findings:
        out.append(f"## [{f['severity'].upper()}] {f['title']}")
        out.append("")
        out.append(f"- **type:** `{f['type']}`")
        out.append(f"- **source:** {tier_label(f.get('tier', 'ast'))}")
        if f["impactedFlows"]:
            out.append(f"- **impacted flows:** {', '.join(f['impactedFlows'])}")
        if f["evidence"]:
            out.append(f"- **evidence:** `{f['evidence']}`")
        out.append(f"- **artifact:** `{f['artifact']}`")
        out.append("")
        out.append(f["detail"])
        out.append("")
    return "\n".join(out) + "\n"
