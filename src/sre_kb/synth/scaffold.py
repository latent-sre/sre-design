"""Build KB artifact docs (envelope dicts) from collected facts."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import FactSet
from sre_kb.scoring.readiness import readiness_spec
from sre_kb.synth.emit import emit as _doc
from sre_kb.synth.inventory import inventory_docs
from sre_kb.util import member_of, slug


def scaffold(fs: FactSet, ctx: ScanContext) -> list[dict]:
    app = fs.first("pcf.app")
    service = (app.attrs.get("name") if app else None) or "service"
    docs: list[dict] = []

    cb = fs.first("resiliency.circuitbreaker")
    fb = fs.first("resiliency.fallback")
    obs = fs.first("observability.logging")
    slo = fs.first("config.slo")
    flow = fs.first("flow.flow")
    pub = fs.first("message.egress")
    repo = fs.first("db.repository")
    swallowed = fs.first("swallowed.failure")
    budget = fs.of("budget.finding")

    flow_name = slug(member_of(flow.symbol.fqn)) if flow else "flow"
    obs_name = "logging"
    slo_name = slug(slo.attrs["meter"]) if slo else None
    cb_name = slug(cb.attrs["name"]) if cb else None
    alert_name = f"{slug(pub.attrs['channel'])}-publish-failures" if (pub and swallowed) else None

    # --- ResiliencyPattern ---
    if cb:
        docs.append(
            _doc(
                "ResiliencyPattern",
                cb.attrs["name"],
                {
                    "type": "circuit-breaker",
                    "library": cb.attrs.get("library", "resilience4j"),
                    "targetSymbol": cb.attrs.get("targetSymbol"),
                    "fallbackMethod": cb.attrs.get("fallbackMethod"),
                },
                [cb.evidence],
                "verified",
                0.9,
                service,
            )
        )

    # --- Fallback ---
    if fb:
        docs.append(
            _doc(
                "Fallback",
                f"{fb.attrs['forTarget']}-fallback",
                {
                    "trigger": "exception-or-circuit-open",
                    "fallbackSymbol": fb.attrs.get("method"),
                    "behavior": "degraded",
                    "forTarget": fb.attrs.get("forTarget"),
                },
                [fb.evidence],
                "verified",
                0.85,
                service,
            )
        )

    # --- Observability (logging sub-section) ---
    if obs:
        docs.append(
            _doc(
                "Observability",
                obs_name,
                {
                    "logging": {
                        "framework": obs.attrs.get("framework"),
                        "format": obs.attrs.get("format"),
                        "pattern": obs.attrs.get("pattern"),
                        "correlationFields": obs.attrs.get("correlationFields", []),
                    }
                },
                [obs.evidence],
                "verified",
                0.9,
                service,
            )
        )

    # --- SloSli (detect-or-needs-review) ---
    if slo:
        docs.append(
            _doc(
                "SloSli",
                slo_name,
                {
                    "objectives": [
                        {
                            "sli": "latency",
                            "meter": slo.attrs.get("meter"),
                            "buckets": slo.attrs.get("buckets"),
                            "target": None,
                            "window": None,
                        }
                    ],
                    "source": "code/config",
                    "forFlow": flow_name,
                },
                [slo.evidence],
                "needs-review",
                0.5,
                service,
            )
        )

    # --- Flow ---
    if flow:
        steps = [
            {"id": s["id"], "name": s["name"], "kind": s["kind"], "failureModes": s["failureModes"]}
            for s in flow.attrs["steps"]
        ]
        flow_ev = [flow.evidence] + [
            ctx.evidence(flow.attrs["path"], s["line"], s["line"], "java_spring.flow_builder")
            for s in flow.attrs["steps"]
        ]
        cross: list[dict] = []
        for s in flow.attrs["steps"]:
            cross.extend(s.get("refs", []))
        if fb:
            cross.append({"kind": "Fallback", "name": slug(f"{fb.attrs['forTarget']}-fallback"), "relation": "depends-on"})
        spec = {
            "trigger": flow.attrs["trigger"],
            "steps": steps,
            "sinks": flow.attrs["sinks"],
        }
        if slo_name:
            spec["sloRef"] = slo_name
        docs.append(_doc("Flow", flow_name, spec, flow_ev, "verified", 0.85, service, cross))

    # --- BlastRadius (minimal, per sink node) ---
    if flow:
        if cb:
            docs.append(
                _doc(
                    "BlastRadius",
                    cb.attrs["name"],
                    {
                        "node": {"type": "service", "name": cb.attrs["name"]},
                        "impactedFlows": [flow_name],
                        "containment": [
                            {"kind": "ResiliencyPattern", "name": cb_name},
                            *([{"kind": "Fallback", "name": slug(f"{fb.attrs['forTarget']}-fallback")}] if fb else []),
                        ],
                        "dependencyCriticality": "contained",
                        "severityHint": "medium",
                    },
                    [cb.evidence],
                    "verified",
                    0.8,
                    service,
                )
            )
        if repo:
            docs.append(
                _doc(
                    "BlastRadius",
                    slug(repo.attrs["name"]),
                    {
                        "node": {"type": "datastore", "name": slug(repo.attrs["name"])},
                        "impactedFlows": [flow_name],
                        "containment": [],
                        "stateful": {"dataLossRisk": False},
                        "dependencyCriticality": "critical",
                        "severityHint": "high",
                    },
                    [repo.evidence],
                    "verified",
                    0.8,
                    service,
                )
            )
        if pub:
            data_loss = bool(swallowed)
            docs.append(
                _doc(
                    "BlastRadius",
                    slug(pub.attrs["channel"]),
                    {
                        "node": {"type": "broker", "name": pub.attrs["channel"]},
                        "impactedFlows": [flow_name],
                        "containment": [],
                        "stateful": {"dataLossRisk": data_loss},
                        "dependencyCriticality": "critical" if data_loss else "normal",
                        "severityHint": "high" if data_loss else "medium",
                    },
                    [swallowed.evidence if swallowed else pub.evidence],
                    "verified",
                    0.8,
                    service,
                )
            )

    # --- Alert (from swallowed failure) ---
    if alert_name and swallowed:
        search = swallowed.attrs["message"].split("{")[0].strip()
        docs.append(
            _doc(
                "Alert",
                alert_name,
                {
                    "alertType": "threshold",
                    "sloRef": None,
                    "signalSource": "log-pattern",
                    "severity": "high",
                    "forFlow": flow_name,
                    "logFormatRef": obs_name,
                    "expr": {
                        "splunk": f'index=app sourcetype={service} "{search}" | stats count by host',
                        "prometheus": None,
                    },
                    "rationale": (
                        "Publish failure is logged and swallowed (data-loss risk); no metric "
                        "exists, so alert on the log line. Add a counter + burn-rate alert once "
                        "an SLO is defined (needs-review)."
                    ),
                },
                [swallowed.evidence] + ([obs.evidence] if obs else []),
                "needs-review",
                0.6,
                service,
                cross_refs=[{"kind": "Flow", "name": flow_name, "relation": "alerts-on"}],
            )
        )

    # --- Runbook (for the alert) ---
    if alert_name and swallowed:
        docs.append(
            _doc(
                "Runbook",
                alert_name,
                {
                    "banner": "GENERATED — verify before executing",
                    "trigger": {"alertRef": alert_name},
                    "symptoms": [
                        f"'{swallowed.attrs['message'].split('{')[0].strip()}' appears in logs",
                        f"{pub.attrs['channel']} events missing downstream while orders persist",
                    ],
                    "diagnosis": [
                        {"step": "Check the order-kafka service binding and broker health"},
                        {"step": "Inspect the publisher catch block (failure is swallowed)"},
                    ],
                    "remediation": [
                        "Verify the order-kafka binding and broker availability",
                        "No built-in replay: missing events are lost — assess impact window",
                        "Code change: make publish transactional / add an outbox (follow-up)",
                    ],
                    "escalation": "service owner (needs-review)",
                    "relatedFlow": flow_name,
                },
                [swallowed.evidence],
                "needs-review",
                0.6,
                service,
                cross_refs=[
                    {"kind": "Alert", "name": alert_name, "relation": "covers"},
                    {"kind": "Flow", "name": flow_name, "relation": "covers"},
                ],
            )
        )

    # --- ServiceCatalogEntry ---
    if app:
        docs.append(
            _doc(
                "ServiceCatalogEntry",
                service,
                {
                    "type": "service",
                    "lifecycle": "production",
                    "providesApis": [flow.attrs["trigger"]["path"]] if flow else [],
                    "dependsOn": app.attrs.get("services", []),
                },
                [app.evidence],
                "verified",
                0.8,
                service,
            )
        )

    # --- P2 inventory kinds (TechStack, Deployment, Dependency, Interface, DataStore, ConfigManagement) ---
    docs.extend(inventory_docs(fs, ctx, service))

    # --- ReadinessScore (coverage roll-up) ---
    docs.append(
        _doc(
            "ReadinessScore",
            service,
            readiness_spec(fs, docs, budget),
            [],
            "needs-review",
            0.6,
            service,
        )
    )

    return docs
