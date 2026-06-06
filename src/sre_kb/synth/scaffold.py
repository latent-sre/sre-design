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
    budget = fs.of("budget.finding")

    flow_name = slug(member_of(flow.symbol.fqn)) if flow else "flow"
    obs_name = "logging"
    slo_name = slug(slo.attrs["meter"]) if slo else None
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

    # --- Flow (one per endpoint) ---
    flows = fs.of("flow.flow")
    cbs = fs.of("resiliency.circuitbreaker")
    repos = fs.of("db.repository")
    pubs = fs.of("message.egress")
    swallowed_by_channel = {s.attrs.get("channel"): s for s in fs.of("swallowed.failure")}

    for ff in flows:
        fname = ff.attrs["name"]
        steps = [
            {"id": s["id"], "name": s["name"], "kind": s["kind"], "failureModes": s["failureModes"]}
            for s in ff.attrs["steps"]
        ]
        flow_ev = [ff.evidence] + [
            ctx.evidence(ff.attrs["path"], s["line"], s["line"], "java_spring.flow_builder")
            for s in ff.attrs["steps"]
        ]
        cross: list[dict] = []
        for s in ff.attrs["steps"]:
            cross.extend(s.get("refs", []))
        if fb and any(s["kind"] == "http-egress" for s in ff.attrs["steps"]):
            cross.append({"kind": "Fallback", "name": slug(f"{fb.attrs['forTarget']}-fallback"), "relation": "depends-on"})
        spec = {"trigger": ff.attrs["trigger"], "steps": steps, "sinks": ff.attrs["sinks"]}
        if slo_ref and fname == flow_name:
            spec["sloRef"] = slo_ref
        docs.append(_doc("Flow", fname, spec, flow_ev, "verified", confidence(Signal.DERIVED, len(flow_ev)), service, cross))

    # --- BlastRadius (one per dependency node, impactedFlows aggregated across flows) ---
    def _flows_touching(node_slug: str) -> list[str]:
        return [
            ff.attrs["name"]
            for ff in flows
            if any(slug(str(sk.get("target"))) == node_slug for sk in ff.attrs.get("sinks", []))
        ]

    for cb_f in cbs:
        impacted = _flows_touching(slug(cb_f.attrs["name"]))
        if not impacted:
            continue
        containment = [{"kind": "ResiliencyPattern", "name": slug(cb_f.attrs["name"])}]
        if fb:
            containment.append({"kind": "Fallback", "name": slug(f"{fb.attrs['forTarget']}-fallback")})
        docs.append(_doc("BlastRadius", cb_f.attrs["name"], {
            "node": {"type": "service", "name": cb_f.attrs["name"]},
            "impactedFlows": impacted,
            "containment": containment,
            "dependencyCriticality": "contained",
            "severityHint": "medium",
        }, [cb_f.evidence], "verified", confidence(Signal.DERIVED, len(impacted)), service))

    for repo_f in repos:
        node = slug(repo_f.attrs["name"])
        impacted = _flows_touching(node)
        if not impacted:
            continue
        docs.append(_doc("BlastRadius", node, {
            "node": {"type": "datastore", "name": node},
            "impactedFlows": impacted,
            "containment": [],
            "stateful": {"dataLossRisk": False},
            "dependencyCriticality": "critical",
            "severityHint": "high",
        }, [repo_f.evidence], "verified", confidence(Signal.DERIVED, len(impacted)), service))

    for pub_f in pubs:
        channel = pub_f.attrs["channel"]
        impacted = _flows_touching(slug(channel))
        if not impacted:
            continue
        sw = swallowed_by_channel.get(channel)
        data_loss = bool(sw)
        docs.append(_doc("BlastRadius", slug(channel), {
            "node": {"type": "broker", "name": channel},
            "impactedFlows": impacted,
            "containment": [],
            "stateful": {"dataLossRisk": data_loss},
            "dependencyCriticality": "critical" if data_loss else "normal",
            "severityHint": "high" if data_loss else "medium",
        }, [sw.evidence if sw else pub_f.evidence], "verified", confidence(Signal.DERIVED, len(impacted)), service))

    # --- Alert + Runbook, one per swallowed publish channel ---
    for channel, sw in swallowed_by_channel.items():
        if not any(p.attrs.get("channel") == channel for p in pubs):
            continue
        a_name = f"{slug(channel)}-publish-failures"
        impacted = _flows_touching(slug(channel))
        for_flow = impacted[0] if impacted else flow_name
        search = sw.attrs["message"].split("{")[0].strip()
        docs.append(_doc("Alert", a_name, {
            "alertType": "threshold",
            "sloRef": None,
            "signalSource": "log-pattern",
            "severity": "high",
            "forFlow": for_flow,
            "logFormatRef": obs_name,
            "expr": {
                "splunk": f'index=app sourcetype={service} "{search}" | stats count by host',
                "prometheus": None,
            },
            "rationale": (
                "Publish failure is logged and swallowed (data-loss risk); no metric exists, so "
                "alert on the log line. Add a counter + burn-rate alert once an SLO is defined "
                "(needs-review)."
            ),
        }, [sw.evidence] + ([obs.evidence] if obs else []), "needs-review", confidence(Signal.INFERRED),
            service, cross_refs=[{"kind": "Flow", "name": for_flow, "relation": "alerts-on"}]))
        docs.append(_doc("Runbook", a_name, {
            "banner": "GENERATED — verify before executing",
            "trigger": {"alertRef": a_name},
            "symptoms": [
                f"'{search}' appears in logs",
                f"{channel} events missing downstream while orders persist",
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
            "relatedFlow": for_flow,
        }, [sw.evidence], "needs-review", confidence(Signal.INFERRED), service,
            cross_refs=[{"kind": "Alert", "name": a_name, "relation": "covers"},
                        {"kind": "Flow", "name": for_flow, "relation": "covers"}]))

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
                confidence(Signal.DERIVED),  # computed from the SLO objective
                service,
                cross_refs=[
                    {"kind": "Flow", "name": flow_name, "relation": "alerts-on"},
                    {"kind": "SloSli", "name": slo_ref, "relation": "alerts-on"},
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
