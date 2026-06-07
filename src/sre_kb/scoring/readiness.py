"""PRR-style readiness checks + KB-coverage roll-up over the scaffolded artifacts."""

from __future__ import annotations

from sre_kb.models.facts import FactSet


def _grade(score: float) -> str:
    return "A" if score >= 0.9 else "B" if score >= 0.75 else "C" if score >= 0.6 else "D" if score >= 0.4 else "F"


def _verified(docs: list[dict], kind: str, pred=None) -> bool:
    """True iff a VERIFIED artifact of `kind` exists (optionally matching `pred`). A PRR
    control backed only by a needs-review/rejected artifact is not a control yet, so it must
    not credit the grade — that was the readiness inflation the trust spine had to close."""
    return any(
        d.get("kind") == kind and d.get("status") == "verified" and (pred is None or pred(d))
        for d in docs
    )


def _exists(docs: list[dict], kind: str) -> bool:
    return any(d.get("kind") == kind for d in docs)


def readiness_spec(fs: FactSet, docs: list[dict], budget_findings: list) -> dict:
    app = fs.first("pcf.app")
    kinds = [d["kind"] for d in docs]

    checks = {
        "healthcheck": bool(app and (app.attrs.get("healthCheck") or {}).get("type")),
        "structured-logging": bool(fs.first("observability.logging")),
        "metrics-exposed": bool(fs.first("config.actuator")),
        "tracing-enabled": False,  # no Sleuth/OTel detected
        "timeout-on-egress": bool(fs.first("config.timelimiter") or fs.first("config.client")),
        "circuit-breaker-on-egress": bool(fs.first("resiliency.circuitbreaker")),
        "fallback-defined": bool(fs.first("resiliency.fallback")),
        "slo-target-defined": bool(fs.first("slo.objective")),
        # Artifact-backed controls credit the grade only when the artifact is VERIFIED.
        "burn-rate-alert": _verified(
            docs, "Alert", lambda d: (d.get("spec") or {}).get("alertType") == "burn-rate"
        ),
        "alert-for-top-flow": _verified(docs, "Alert"),
        "runbook-for-top-flow": _verified(docs, "Runbook"),
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
    # A drafted-but-unverified control is a gap, not a pass.
    if not checks["alert-for-top-flow"] and _exists(docs, "Alert"):
        gaps.append("An Alert exists but is not verified (needs-review)")
    if not checks["runbook-for-top-flow"] and _exists(docs, "Runbook"):
        gaps.append("A Runbook exists but is not verified (needs-review)")

    return {
        "prrChecks": checks,
        "score": score,
        "grade": _grade(score),
        "coverage": {
            "flows": len(fs.of("flow.flow")),
            "flowsWithAlerts": sum(1 for d in docs if d["kind"] == "Alert"),
            "kinds": len(set(kinds)),
            "needsReview": sum(1 for d in docs if d.get("status") == "needs-review"),
        },
        "gaps": gaps,
    }
