"""Deterministic five-pass report for non-developer and SRE readers."""

from __future__ import annotations

from collections import Counter

PASS_NAMES = (
    "What is this system?",
    "How does work move through it?",
    "What does it depend on?",
    "How does it fail and recover?",
    "What should people do next?",
)


def _ref(doc: dict) -> str:
    return f"{doc.get('kind', 'Artifact')}/{(doc.get('metadata') or {}).get('name', 'unknown')}"


def _flow_line(doc: dict) -> str:
    spec = doc.get("spec") or {}
    trigger = spec.get("trigger") or {}
    request = " ".join(str(trigger.get(k, "")).strip() for k in ("method", "path")).strip()
    steps, sinks = spec.get("steps") or [], spec.get("sinks") or []
    targets = [str(s["target"]) for s in sinks if isinstance(s, dict) and s.get("target")]
    start = f"A request to `{request}`" if request else "A trigger"
    end = f" and reaches {', '.join(f'`{x}`' for x in targets[:4])}" if targets else ""
    return f"{start} runs {len(steps)} recorded step(s){end}."


def _dependency_line(doc: dict) -> str:
    """Explain one dependency using only fields already carried by its validated artifact."""
    spec = doc.get("spec") or {}
    name = spec.get("name") or (doc.get("metadata") or {}).get("name", "unknown")
    kind = spec.get("type", "dependency")
    destination = spec.get("baseUrl")
    engine = spec.get("engine")
    source = spec.get("source")
    detail = f" ({engine})" if engine else ""
    endpoint = f" at `{destination}`" if destination else ""
    declared = f"; declared by `{source}`" if source else ""
    return (f"`{name}` is a {kind}{detail}{endpoint}{declared}. Artifact `{_ref(doc)}` is "
            f"{doc.get('status', 'unknown')}.")


def build_human_report(service: str, run_id: str, docs: list[dict], findings: list[dict]) -> dict:
    """Ask five progressively deeper questions of the already validated KB."""
    verified = [d for d in docs if d.get("status") == "verified"]
    kinds = Counter(d.get("kind", "Unknown") for d in docs)
    flows = [d for d in docs if d.get("kind") == "Flow"]
    dependencies = [d for d in docs if d.get("kind") == "Dependency"]
    blast_views = [d for d in docs if d.get("kind") == "BlastRadius"]
    protections = [d for d in docs if d.get("kind") in {"ResiliencyPattern", "Fallback", "Messaging"}]
    gaps = [d for d in docs if d.get("kind") == "ResiliencyGap"]
    high = [f for f in findings if f.get("severity") in {"critical", "high"}]
    passes = [
        {"number": 1, "name": PASS_NAMES[0],
         "answer": (f"`{service}` is represented by {len(docs)} artifact(s): {len(verified)} verified "
                    f"and {len(docs) - len(verified)} requiring review. This is repository evidence, "
                    "not a live health observation."),
         "details": [f"{k}: {v}" for k, v in sorted(kinds.items())],
         "evidence": [_ref(d) for d in docs[:8]]},
        {"number": 2, "name": PASS_NAMES[1],
         "answer": (f"The scan found {len(flows)} end-to-end flow(s)." if flows else
                    "No end-to-end Flow artifact was established by this scan."),
         "details": [_flow_line(d) for d in flows[:8]], "evidence": [_ref(d) for d in flows[:8]]},
        {"number": 3, "name": PASS_NAMES[2],
         "answer": (f"The KB contains {len(dependencies)} external dependency artifact(s) and "
                    f"{len(blast_views)} blast-radius view(s). Service destinations are shown only "
                    "when code or configuration supplied them."),
         "details": ([_dependency_line(d) for d in dependencies[:8]] +
                     [f"Failure impact: `{_ref(d)}` is {d.get('status', 'unknown')}."
                      for d in blast_views[:8]]),
         "evidence": [_ref(d) for d in (dependencies[:8] + blast_views[:8])]},
        {"number": 4, "name": PASS_NAMES[3],
         "answer": (f"The scan found {len(protections)} resilience protection artifact(s) and "
                    f"{len(gaps)} resilience gap artifact(s). Presence is not proof that a mechanism "
                    "is enabled, correctly tuned, or effective in production."),
         "details": [*(f"Protection: `{_ref(d)}` ({d.get('status', 'unknown')})."
                       for d in protections[:5]),
                     *(f"Gap: `{_ref(d)}` ({d.get('status', 'unknown')})." for d in gaps[:5])],
         "evidence": [_ref(d) for d in protections[:5] + gaps[:5]]},
        {"number": 5, "name": PASS_NAMES[4],
         "answer": (f"There are {len(findings)} ranked finding(s), including {len(high)} critical/high. "
                    "Review cited artifacts first, then confirm current impact with telemetry and an operator."),
         "details": [f"[{f.get('severity', 'unknown').upper()}] "
                     f"{f.get('title', f.get('type', 'Finding'))} — "
                     f"`{f.get('artifact', 'no-artifact')}`" for f in findings[:10]],
         "evidence": [f["artifact"] for f in findings[:10] if f.get("artifact")]},
    ]
    return {"apiVersion": "sre.kb/human-report/v1alpha1", "service": service, "runId": run_id,
            "evidenceBoundary": ("Static and declared repository evidence unless an artifact explicitly "
                                 "says otherwise; no claim of current production health."),
            "passes": passes}


def render_human_report(report: dict) -> str:
    """Render a skimmable Markdown report while retaining artifact references."""
    lines = [f"# Five-pass system report — {report['service']}", "",
             f"> **Evidence boundary:** {report['evidenceBoundary']}", ""]
    for item in report["passes"]:
        lines += [f"## Pass {item['number']} — {item['name']}", "", item["answer"], ""]
        lines += [*(f"- {x}" for x in item["details"]), ""] if item["details"] else []
        if item["evidence"]:
            lines += ["**Traceable artifacts:** " + ", ".join(f"`{r}`" for r in item["evidence"]), ""]
    lines += ["## Operator checkpoint", "",
              "Before acting, verify artifact status and cited source. Use metrics, logs, traces, "
              "deployment state, and SLOs to establish what is happening now."]
    return "\n".join(lines) + "\n"
