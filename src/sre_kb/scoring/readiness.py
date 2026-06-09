"""PRR-style readiness checks + KB-coverage roll-up over the scaffolded artifacts."""

from __future__ import annotations

from sre_kb.inventory_signatures import is_tracing_dependency
from sre_kb.models.facts import FactSet


def _grade(score: float) -> str:
    return "A" if score >= 0.9 else "B" if score >= 0.75 else "C" if score >= 0.6 else "D" if score >= 0.4 else "F"


def _has_verified(docs: list[dict], kind: str, pred=None) -> bool:
    """True iff a VERIFIED artifact of `kind` (matching `pred`) exists — a needs-review draft
    must not inflate readiness (HYBRID-PLAN §4/Phase 2). 'Present but unverified' is a gap."""
    return any(
        d.get("kind") == kind and d.get("status") == "verified" and (pred is None or pred(d))
        for d in docs
    )


def readiness_spec(fs: FactSet, docs: list[dict], budget_findings: list) -> dict:
    app = fs.first("pcf.app")
    kinds = [d["kind"] for d in docs]
    # Tracing is wired iff a distributed-tracing library is a dependency — the same data-driven check
    # the gap-finder's missing-tracing refutation uses, so the PRR check can't drift from it (R6).
    tracing = any(is_tracing_dependency(str(d.attrs.get("name", ""))) for d in fs.of("tech.dependency"))

    checks = {
        "healthcheck": bool(app and (app.attrs.get("healthCheck") or {}).get("type")),
        "structured-logging": bool(fs.first("observability.logging")),
        "metrics-exposed": bool(fs.first("config.actuator")),
        "tracing-enabled": tracing,
        "timeout-on-egress": bool(fs.first("config.timelimiter") or fs.first("config.client")),
        "circuit-breaker-on-egress": bool(fs.first("resiliency.circuitbreaker")),
        "fallback-defined": bool(fs.first("resiliency.fallback")),
        "slo-target-defined": bool(fs.first("slo.objective")),
        # Artifact-presence checks credit only VERIFIED coverage (status-aware): a needs-review
        # draft is noted as a gap, never counted toward the grade.
        "burn-rate-alert": _has_verified(docs, "Alert", lambda d: (d.get("spec") or {}).get("alertType") == "burn-rate"),
        "alert-for-top-flow": _has_verified(docs, "Alert"),
        "runbook-for-top-flow": _has_verified(docs, "Runbook"),
    }
    passed = sum(1 for v in checks.values() if v)
    score = round(passed / len(checks), 2)

    gaps: list[str] = [f.attrs["detail"] for f in budget_findings]
    if not checks["slo-target-defined"]:
        gaps.append("No SLO target/window defined (needs-review)")
    if not checks["tracing-enabled"]:
        gaps.append("No distributed tracing (Sleuth/OTel) detected")
    if fs.first("swallowed.failure"):
        gaps.append("A publish failure is logged and swallowed — data-loss risk")
    # Distinguish "present but unverified" from "absent" so the reviewer isn't misled.
    if not checks["alert-for-top-flow"] and any(d.get("kind") == "Alert" for d in docs):
        gaps.append("Alert present but not yet verified (needs-review)")
    if not checks["runbook-for-top-flow"] and any(d.get("kind") == "Runbook" for d in docs):
        gaps.append("Runbook present but not yet verified (needs-review)")

    return {
        "prrChecks": checks,
        "score": score,
        "grade": _grade(score),
        "coverage": {
            "flows": len(fs.of("flow.flow")),
            # Distinct flows an Alert actually references (crossRefs kind=Flow) — counting Alert
            # artifacts here read "flows: 1, flowsWithAlerts: 2" when two alerts covered one flow.
            "flowsWithAlerts": len({
                ref.get("name")
                for d in docs if d["kind"] == "Alert"
                for ref in (d.get("crossRefs") or []) if ref.get("kind") == "Flow"
            }),
            "kinds": len(set(kinds)),
            "needsReview": sum(1 for d in docs if d.get("status") == "needs-review"),
        },
        "gaps": gaps,
    }
