"""Findings digest: aggregate the cross-cutting SRE risks the engine already computes
(scattered across BlastRadius artifacts) into one ranked, evidence-linked summary — the
"so what" for an on-call reviewer."""

from __future__ import annotations

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_TYPE_RANK = {"data-loss-risk": 0, "uncontained-critical-dep": 1, "broad-impact-dependency": 2}


def _first_evidence(doc: dict) -> str | None:
    ev = (doc.get("evidence") or [{}])[0]
    if ev.get("path"):
        lines = ev.get("lines") or {}
        return f"{ev['path']}:{lines.get('start')}-{lines.get('end')}"
    return None


def collect_findings(docs: list[dict]) -> list[dict]:
    """Extract ranked risk findings from BlastRadius artifacts (severity-ordered)."""
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
    out.sort(key=lambda f: (_SEV_RANK.get(f["severity"], 9), _TYPE_RANK.get(f["type"], 9), f["title"]))
    return out


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
        lines.append(f"[{f['severity'].upper()}] {f['type']}: {f['title']}")
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
        if f["impactedFlows"]:
            out.append(f"- **impacted flows:** {', '.join(f['impactedFlows'])}")
        if f["evidence"]:
            out.append(f"- **evidence:** `{f['evidence']}`")
        out.append(f"- **artifact:** `{f['artifact']}`")
        out.append("")
        out.append(f["detail"])
        out.append("")
    return "\n".join(out) + "\n"
