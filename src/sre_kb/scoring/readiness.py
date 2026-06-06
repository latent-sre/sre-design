"""PRR-style readiness checks + KB-coverage roll-up over the scaffolded artifacts."""

from __future__ import annotations

from sre_kb.models.facts import FactSet


def _grade(score: float) -> str:
    return "A" if score >= 0.9 else "B" if score >= 0.75 else "C" if score >= 0.6 else "D" if score >= 0.4 else "F"


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
        "burn-rate-alert": any(
            d["kind"] == "Alert" and (d.get("spec") or {}).get("alertType") == "burn-rate" for d in docs
        ),
        "alert-for-top-flow": "Alert" in kinds,
        "runbook-for-top-flow": "Runbook" in kinds,
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
