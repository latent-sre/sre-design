"""PRR-style readiness checks + KB-coverage roll-up over the scaffolded artifacts."""

from __future__ import annotations

from sre_kb.models.facts import FactSet


def readiness_spec(fs: FactSet, docs: list[dict], budget_findings: list) -> dict:
    app = fs.first("pcf.app")
    kinds = [d["kind"] for d in docs]

    checks = {
        "healthcheck": bool(app and (app.attrs.get("healthCheck") or {}).get("type")),
        "structured-logging": bool(fs.first("observability.logging")),
        "timeout-on-egress": bool(fs.first("config.timelimiter") or fs.first("config.client")),
        "circuit-breaker-on-egress": bool(fs.first("resiliency.circuitbreaker")),
        "fallback-defined": bool(fs.first("resiliency.fallback")),
        "alert-for-top-flow": "Alert" in kinds,
        "runbook-for-top-flow": "Runbook" in kinds,
        "slo-target-defined": False,  # SLO buckets exist but no explicit target/window yet
    }
    passed = sum(1 for v in checks.values() if v)
    score = round(passed / len(checks), 2)

    gaps: list[str] = [f.attrs["detail"] for f in budget_findings]
    if fs.first("config.slo"):
        gaps.append("SLO buckets present but no explicit target/window (needs-review)")
    if fs.first("swallowed.failure"):
        gaps.append("A publish failure is logged and swallowed — data-loss risk")

    flows = len(fs.of("flow.flow"))
    alerts = sum(1 for d in docs if d["kind"] == "Alert")
    needs_review = sum(1 for d in docs if d.get("status") == "needs-review")

    return {
        "prrChecks": checks,
        "score": score,
        "coverage": {
            "flows": flows,
            "flowsWithAlerts": alerts,
            "needsReview": needs_review,
        },
        "gaps": gaps,
    }
