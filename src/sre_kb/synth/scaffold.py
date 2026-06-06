"""Build KB artifact docs (envelope dicts) from collected facts."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import FactSet
from sre_kb.scoring.confidence import Signal, confidence
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
    objective = next(
        (o for o in fs.of("slo.objective") if o.attrs.get("flow") == flow_name),
        fs.first("slo.objective"),
    )
    slo_ref = None

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
                confidence(Signal.DIRECT),  # explicit @CircuitBreaker / Polly declaration
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
                confidence(Signal.DIRECT),  # a declared fallback method
                service,
            )
        )

    # --- Observability (logging + metrics + tracing + health) ---
    if obs:
        actuator = fs.first("config.actuator")
        slos = fs.of("config.slo")
        has_prom = any(
            d.attrs.get("name") == "micrometer-registry-prometheus" for d in fs.of("tech.dependency")
        )
        health = []
        if actuator or app:
            health.append("actuator/health")
        hc_endpoint = (app.attrs.get("healthCheck") or {}).get("endpoint") if app else None
        if hc_endpoint:
            health.append(hc_endpoint)
        obs_ev = [obs.evidence]
        if actuator:
            obs_ev.append(actuator.evidence)
        if slos:
            obs_ev.append(slos[0].evidence)
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
                    },
                    "actuatorEndpoints": (
                        [e.strip() for e in str(actuator.attrs["exposure"]).split(",")] if actuator else []
                    ),
                    "metrics": [
                        {
                            "name": s.attrs["meter"],
                            "type": "timer",
                            "slo": s.attrs.get("buckets"),
                            "registry": "prometheus" if has_prom else None,
                        }
                        for s in slos
                    ],
                    "tracing": None,
                    "healthIndicators": health,
                },
                obs_ev,
                "verified",
                confidence(Signal.DIRECT, len(obs_ev)),  # logging/actuator/metrics config present
                service,
            )
        )

    # --- SloSli (full from catalog, else detect-or-needs-review) ---
    if objective:
        target = objective.attrs.get("target")
        budget_pct = round(100 - float(target), 4) if target is not None else None
        slo_ref = slug(f"{flow_name}-latency")
        docs.append(
            _doc(
                "SloSli",
                slo_ref,
                {
                    "objectives": [
                        {
                            "sli": objective.attrs.get("sli", "latency"),
                            "target": target,
                            "window": objective.attrs.get("window"),
                            "percentile": objective.attrs.get("percentile"),
                            "thresholdMs": objective.attrs.get("thresholdMs"),
                            "errorBudgetPct": budget_pct,
                        }
                    ],
                    "source": "catalog",
                    "forFlow": objective.attrs.get("flow", flow_name),
                },
                [objective.evidence],
                "verified",
                confidence(Signal.DIRECT),  # explicit objective from the SLO catalog
                service,
            )
        )
    elif slo:
        slo_ref = slo_name
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
                confidence(Signal.WEAK),  # SLO guessed from metric buckets, no objective
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
        if slo_ref:
            spec["sloRef"] = slo_ref
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

    # --- Alert (SLO error-budget burn-rate, when a full objective exists) ---
    if objective and slo_ref and flow:
        target = objective.attrs.get("target")
        budget_frac = round((100 - float(target)) / 100, 6) if target is not None else 0.01
        metric = "http_server_requests_seconds_count"
        docs.append(
            _doc(
                "Alert",
                f"{flow_name}-latency-burn-rate",
                {
                    "alertType": "burn-rate",
                    "sloRef": slo_ref,
                    "signalSource": "metric",
                    "severity": "high",
                    "forFlow": flow_name,
                    "logFormatRef": None,
                    "expr": {
                        "prometheus_fast": (
                            f'sum(rate({metric}{{outcome!="SUCCESS"}}[1h])) / sum(rate({metric}[1h])) '
                            f"> {round(14.4 * budget_frac, 6)}"
                        ),
                        "prometheus_slow": (
                            f'sum(rate({metric}{{outcome!="SUCCESS"}}[6h])) / sum(rate({metric}[6h])) '
                            f"> {round(6 * budget_frac, 6)}"
                        ),
                        "windows": "multi-window (1h fast @14.4x, 6h slow @6x)",
                    },
                    "rationale": (
                        f"Multi-window error-budget burn-rate against SLO target {target}% "
                        f"(budget {round(budget_frac * 100, 3)}%) on the {flow_name} flow."
                    ),
                },
                [objective.evidence] + ([slo.evidence] if slo else []),
                "verified",
                0.8,
                service,
                cross_refs=[
                    {"kind": "Flow", "name": flow_name, "relation": "alerts-on"},
                    {"kind": "SloSli", "name": slo_ref, "relation": "alerts-on"},
                ],
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
                confidence(Signal.DIRECT),  # from the PCF manifest
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
            confidence(Signal.INFERRED),  # a coverage roll-up, not a source fact
            service,
        )
    )

    return docs
