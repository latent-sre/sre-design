"""Build KB artifact docs (envelope dicts) from collected facts."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.config import load_config
from sre_kb.models.facts import FactSet
from sre_kb.render.alerts import (
    BURN_WINDOWS,
    BurnRateIntent,
    LogPatternIntent,
    effective_severity,
    render_burn_rate,
    render_log_pattern,
    rendered_targets,
)
from sre_kb.render.dashboards import red_panels
from sre_kb.scoring.confidence import Signal, confidence
from sre_kb.scoring.readiness import readiness_spec
from sre_kb.scoring.risk import assess as assess_risk
from sre_kb.synth.emit import emit as _doc
from sre_kb.synth.inventory import inventory_docs
from sre_kb.tiers import AST
from sre_kb.util import member_of, slug


def _burn_rate_summary(slo_ref: str, sli: str, budget_frac: float) -> dict:
    """Human-readable burn-rate summary for the Alert spec. Windows and multipliers are derived from
    the single source of truth (alerts.BURN_WINDOWS) so this summary can't desync from the rendered
    PromQL — the multipliers used to be re-typed (14.4/6) here (#M3). shortWindow/longWindow are the
    fast (short-term) and slow (long-term) rate windows; each factor is that rate's multiplier scaled
    by the error budget."""
    rates = {key: (long_w, short_w, mult) for key, long_w, short_w, mult in BURN_WINDOWS}
    fast_long, _, fast_mult = rates["fast"]
    slow_long, _, slow_mult = rates["slow"]
    return {
        "sloRef": slo_ref,
        "sli": "latency" if sli == "latency" else "availability",
        "shortWindow": fast_long,
        "longWindow": slow_long,
        "shortFactor": round(fast_mult * budget_frac, 6),
        "longFactor": round(slow_mult * budget_frac, 6),
        "budgetFraction": budget_frac,
    }


def _logging_statements_summary(log_stmts: list, log_fws: list) -> dict:
    """Roll the parsed log-statement facts (S2) into the Observability `logging.statements` block."""
    by_level: dict[str, int] = {}
    for s in log_stmts:
        lvl = s.attrs.get("level")
        if lvl:
            by_level[lvl] = by_level.get(lvl, 0) + 1
    apis = sorted({f.attrs.get("framework") for f in log_fws if f.attrs.get("framework")})
    return {
        "total": len(log_stmts),
        "byLevel": by_level,
        "loggingApis": apis,
        "parameterized": sum(1 for s in log_stmts if s.attrs.get("parameterized")),
    }


def _logging_quality(fs: FactSet, log_stmts: list) -> tuple[dict, list]:
    """Deterministic logging-quality assessment (S2): request/trace-ID correlation context (from the
    logback `%X{}` fields) and byte-grounded alert-fatigue signals. Returns (quality, error_stmts) so
    the caller can cite a representative error statement that backs the alert-fatigue signal."""
    corr_fields = sorted({
        c for f in fs.of("observability.logging") for c in (f.attrs.get("correlationFields") or [])
    })
    has_context = bool(corr_fields)
    with_msg = [s for s in log_stmts if s.attrs.get("hasMessage")]
    parameterized = [s for s in with_msg if s.attrs.get("parameterized")]
    error_stmts = [s for s in log_stmts if s.attrs.get("level") == "error"]
    signals: list[str] = []
    # Errors you can't correlate to a request/trace are the classic alert-fatigue trap — a paged
    # error with no traceId/requestId can't be triaged. Both signals are byte-grounded in the facts.
    if error_stmts and not has_context:
        signals.append("error-logging-without-correlation-context")
    if len(with_msg) > len(parameterized):
        signals.append("non-parameterized-messages")
    quality = {
        "correlationContext": has_context,
        "correlationFields": corr_fields,
        "placeholderHygiene": (
            round(len(parameterized) / len(with_msg), 4) if with_msg else None
        ),
        "alertFatigueSignals": signals,
    }
    return quality, error_stmts


def _configured_alert_tools() -> tuple[str, ...] | None:
    """The monitoring backends to render alert exprs for (`render.alert_tools`); None = adapter
    defaults, so an unconfigured engine keeps emitting Prometheus + Splunk as before."""
    cfg = (load_config().get("render") or {}).get("alert_tools")
    return tuple(cfg) if cfg else None


def burn_rate_expr(
    sli: str,
    threshold_ms: float | int | None,
    budget_frac: float,
    uri: str | None,
    tools: tuple[str, ...] | None = None,
    percentile: int | float | None = None,
) -> tuple[dict, str]:
    """Multi-window burn-rate expr that measures the SLO's OWN SLI, scoped to the flow's route.

    Thin wrapper over the tool-neutral adapter seam (`render/alerts.py`): builds a `BurnRateIntent`
    and renders it across the selected backends (`tools`; None = adapter defaults). latency ->
    fraction of requests slower than the threshold from the histogram buckets; else -> error
    fraction for availability/error-rate SLIs. Returns `(expr_dict, numerator_phrase)`.
    """
    intent = BurnRateIntent(sli, threshold_ms, budget_frac, uri, percentile)
    return render_burn_rate(intent, tools), intent.numerator


def scaffold(fs: FactSet, ctx: ScanContext) -> list[dict]:
    app = fs.first("pcf.app")
    service = (app.attrs.get("name") if app else None) or "service"
    alert_tools = _configured_alert_tools()
    docs: list[dict] = []

    # --- Criticality (R1) + the severity floor it feeds (R2) ---
    # tier/businessCriticality come from a declaration (authoritative `.sre/criticality.yaml` =
    # Tier-A, or a Copilot `.sre/criticality-proposal.yaml` = Tier-B); dataClassification is the
    # union of any declared classes and the ones the engine deterministically detected in code.
    crit_decl = fs.first("criticality.declared")
    crit_dc = fs.of("criticality.dataclass")
    floor_tier: str | None = None
    if crit_decl or crit_dc:
        da = crit_decl.attrs if crit_decl else {}
        decl_tier = da.get("tier", "unknown")
        # A declaration is Tier-B only when it came from a Copilot proposal (llm evidence). An
        # LLM-proposed tier stays advisory (§7.2): surfaced for review (needs-review), never amplified
        # into paging. An authoritative declaration and the detected data classes are byte-grounded.
        is_proposal = bool(crit_decl) and crit_decl.evidence.source_tier != AST
        classes = set(da.get("dataClassification") or []) | {f.attrs["classification"] for f in crit_dc}
        crit_spec: dict = {"tier": decl_tier, "source": da.get("source", "inferred")}
        if da.get("businessCriticality"):
            crit_spec["businessCriticality"] = da["businessCriticality"]
        if classes:
            crit_spec["dataClassification"] = sorted(classes)
        crit_ev = ([crit_decl.evidence] if crit_decl else []) + [f.evidence for f in crit_dc]
        docs.append(_doc(
            "Criticality", service, crit_spec, crit_ev,
            "needs-review" if is_proposal else "verified",
            confidence(Signal.INFERRED if is_proposal else Signal.DIRECT), service,
        ))
        # Only a byte-grounded (Tier-A) tier feeds the deterministic severity floor (R2).
        floor_tier = decl_tier if (crit_decl and not is_proposal) else None

    cb = fs.first("resiliency.circuitbreaker")
    fb = fs.first("resiliency.fallback")
    obs = fs.first("observability.logging")
    log_stmts = fs.of("observability.log.statement")
    log_fws = fs.of("observability.log.framework")
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
    # Emit when there is a logback config (obs) OR parsed log statements (S2): a service on Spring
    # Boot's default logging has no logback file but still has statements worth assessing.
    if obs or log_stmts:
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

        quality, error_stmts = _logging_quality(fs, log_stmts)
        stmts_summary = _logging_statements_summary(log_stmts, log_fws)
        # Without a logback file, name the framework from the code-detected API and mark the format
        # as Spring Boot's default (the deterministic statements still ground level + quality).
        default_framework = stmts_summary["loggingApis"][0] if stmts_summary["loggingApis"] else "unknown"
        logging_spec = {
            "framework": obs.attrs.get("framework") if obs else default_framework,
            "format": obs.attrs.get("format") if obs else "default",
            "pattern": obs.attrs.get("pattern") if obs else None,
            "correlationFields": quality["correlationFields"],
        }
        if log_stmts:
            logging_spec["statements"] = stmts_summary
            logging_spec["quality"] = quality

        obs_ev = [obs.evidence] if obs else []
        if actuator:
            obs_ev.append(actuator.evidence)
        if slos:
            obs_ev.append(slos[0].evidence)
        # Ground the statement-derived signals: cite the framework import + a representative error
        # statement (the one the alert-fatigue signal is about), falling back to any statement.
        if log_fws:
            obs_ev.append(log_fws[0].evidence)
        if error_stmts:
            obs_ev.append(error_stmts[0].evidence)
        elif log_stmts:
            obs_ev.append(log_stmts[0].evidence)
        docs.append(
            _doc(
                "Observability",
                obs_name,
                {
                    "logging": logging_spec,
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

    # --- Messaging (consumer-side async resilience, S3) ---
    consumers = fs.of("message.consumer")
    if consumers:
        docs.append(
            _doc(
                "Messaging",
                "messaging",
                {
                    "consumers": [
                        {
                            "channel": c.attrs["channel"],
                            "broker": c.attrs["broker"],
                            "handler": c.attrs["handler"],
                            "resilience": {
                                "deadLetter": c.attrs.get("deadLetter", False),
                                "deadLetterMechanism": c.attrs.get("deadLetterMechanism"),
                                "retry": c.attrs.get("retry", False),
                                "idempotentConsumer": c.attrs.get("idempotentConsumer", False),
                            },
                        }
                        for c in consumers
                    ]
                },
                [c.evidence for c in consumers],
                "verified",
                confidence(Signal.DIRECT, len(consumers)),  # listener annotations are explicit
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
                unverified_against_live=True,  # the SLO target/threshold can't be checked offline
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
        risk = assess_risk(impacted_flows=len(impacted), data_loss=False, contained=True)
        docs.append(_doc("BlastRadius", cb_f.attrs["name"], {
            "node": {"type": "service", "name": cb_f.attrs["name"]},
            "impactedFlows": impacted,
            "containment": containment,
            "dependencyCriticality": risk.criticality,
            "severityHint": risk.severity,
            "riskRationale": risk.rationale,
        }, [cb_f.evidence], "verified", confidence(Signal.DERIVED, len(impacted)), service))

    def _lossy_sink(node_slug: str) -> bool:
        """A flow step writing to `node_slug` whose failure is logged-and-swallowed: data loss.
        Steps and sinks are index-parallel only when the flow deriver built both from one
        ordered walk — nothing validates that shape, so a flow with unequal lengths (e.g.
        hand-authored) derives nothing (the safe lower bound) instead of mispairing."""
        return any(
            slug(str(sink.get("target"))) == node_slug
            and any(fm.get("dataLossRisk") for fm in step.get("failureModes", []))
            for ff in flows
            if len(ff.attrs.get("steps", [])) == len(ff.attrs.get("sinks", []))
            for step, sink in zip(ff.attrs.get("steps", []), ff.attrs.get("sinks", []))
        )

    for repo_f in repos:
        node = slug(repo_f.attrs["name"])
        impacted = _flows_touching(node)
        if not impacted:
            continue
        data_loss = _lossy_sink(node)
        risk = assess_risk(impacted_flows=len(impacted), data_loss=data_loss, contained=False)
        docs.append(_doc("BlastRadius", node, {
            "node": {"type": "datastore", "name": node},
            "impactedFlows": impacted,
            "containment": [],
            "stateful": {"dataLossRisk": data_loss},
            "dependencyCriticality": risk.criticality,
            "severityHint": risk.severity,
            "riskRationale": risk.rationale,
        }, [repo_f.evidence], "verified", confidence(Signal.DERIVED, len(impacted)), service))

    for pub_f in pubs:
        channel = pub_f.attrs["channel"]
        impacted = _flows_touching(slug(channel))
        if not impacted:
            continue
        sw = swallowed_by_channel.get(channel)
        data_loss = bool(sw)
        risk = assess_risk(impacted_flows=len(impacted), data_loss=data_loss, contained=False)
        docs.append(_doc("BlastRadius", slug(channel), {
            "node": {"type": "broker", "name": channel},
            "impactedFlows": impacted,
            "containment": [],
            "stateful": {"dataLossRisk": data_loss},
            "dependencyCriticality": risk.criticality,
            "severityHint": risk.severity,
            "riskRationale": risk.rationale,
        }, [sw.evidence if sw else pub_f.evidence], "verified", confidence(Signal.DERIVED, len(impacted)), service))

    # --- Alert + Runbook, one per swallowed publish channel ---
    for channel, sw in swallowed_by_channel.items():
        if not any(p.attrs.get("channel") == channel for p in pubs):
            continue
        a_name = f"{slug(channel)}-publish-failures"
        impacted = _flows_touching(slug(channel))
        for_flow = impacted[0] if impacted else flow_name
        search = sw.attrs["message"].split("{")[0].strip()
        lp_expr = render_log_pattern(LogPatternIntent(search=search, service=service), alert_tools)
        docs.append(_doc("Alert", a_name, {
            "alertType": "threshold",
            "sloRef": None,
            "signalSource": "log-pattern",
            "severity": effective_severity("high", floor_tier),
            "forFlow": for_flow,
            "logFormatRef": obs_name,
            "expr": lp_expr,
            "rationale": (
                "Publish failure is logged and swallowed (data-loss risk); no metric exists, so "
                "alert on the log line. Add a counter + burn-rate alert once an SLO is defined "
                "(needs-review)."
            ),
            # Tool-neutral intent (adopted from resiliency-skills AlertIntent), on our envelope.
            "class": "cause",
            "signal": {"type": "log", "description": f'swallowed-failure log line "{search}"'},
            "renderTargets": rendered_targets(lp_expr),
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

    # --- Alert + Runbook, one per swallowed repository write (the DB dual of the loop above:
    # the engine just flagged silent write loss, so the Flow->Alert->Runbook chain must exist
    # for it too) ---
    for sw in fs.of("swallowed.db.failure"):
        repo_f = next((r for r in repos if r.attrs["name"] == sw.attrs.get("repository")), None)
        if repo_f is None:
            continue
        node = slug(repo_f.attrs["name"])
        a_name = f"{node}-write-failures"
        impacted = _flows_touching(node)
        for_flow = impacted[0] if impacted else flow_name
        search = sw.attrs["message"].split("{")[0].strip()
        lp_expr = render_log_pattern(LogPatternIntent(search=search, service=service), alert_tools)
        docs.append(_doc("Alert", a_name, {
            "alertType": "threshold",
            "sloRef": None,
            "signalSource": "log-pattern",
            "severity": effective_severity("high", floor_tier),
            "forFlow": for_flow,
            "logFormatRef": obs_name,
            "expr": lp_expr,
            "rationale": (
                "DB write failure is logged and swallowed (silent write loss); no metric exists, "
                "so alert on the log line. Surface the failure or make the write transactional "
                "(needs-review)."
            ),
            "class": "cause",
            "signal": {"type": "log", "description": f'swallowed DB-write log line "{search}"'},
            "renderTargets": rendered_targets(lp_expr),
        }, [sw.evidence] + ([obs.evidence] if obs else []), "needs-review", confidence(Signal.INFERRED),
            service, cross_refs=[{"kind": "Flow", "name": for_flow, "relation": "alerts-on"}]))
        docs.append(_doc("Runbook", a_name, {
            "banner": "GENERATED — verify before executing",
            "trigger": {"alertRef": a_name},
            "symptoms": [
                f"'{search}' appears in logs",
                "writes acknowledged to callers but rows missing downstream",
            ],
            "diagnosis": [
                {"step": "Check the database service binding and datastore health"},
                {"step": "Inspect the save() catch block (failure is swallowed)"},
            ],
            "remediation": [
                "Verify the datastore binding and availability",
                "No automatic replay: writes in the failure window are lost — assess impact",
                "Code change: surface the failure / make the write transactional (follow-up)",
            ],
            "escalation": "service owner (needs-review)",
            "relatedFlow": for_flow,
        }, [sw.evidence], "needs-review", confidence(Signal.INFERRED), service,
            cross_refs=[{"kind": "Alert", "name": a_name, "relation": "covers"},
                        {"kind": "Flow", "name": for_flow, "relation": "covers"}]))

    # --- Alert (SLO burn-rate, when a full objective exists) ---
    # The burn-rate signal must match the SLI the SLO names (latency -> histogram buckets, else
    # error rate) and be scoped to the flow's own route, not measured service-wide.
    sli = (objective.attrs.get("sli") if objective else None) or "latency"
    threshold_ms = objective.attrs.get("thresholdMs") if objective else None
    target = objective.attrs.get("target") if objective else None
    budget_frac = round((100 - float(target)) / 100, 6) if target is not None else 0.01
    # A latency objective needs a concrete threshold to derive a bucket-based expr, AND the SLO must
    # leave a positive error budget — a 100% (or out-of-range) target yields budget <= 0, whose
    # burn-rate threshold would be `> 0` and page on a single request. Skip rather than emit a
    # wrong-signal or pager-storm alert.
    if (
        objective and slo_ref and flow
        and (sli != "latency" or threshold_ms is not None)
        and 0 < budget_frac < 1
    ):
        uri = (flow.attrs.get("trigger") or {}).get("path")
        pct = objective.attrs.get("percentile")
        expr, numerator = burn_rate_expr(sli, threshold_ms, budget_frac, uri, alert_tools, pct)
        scope = f"route {uri}" if uri else f"the {flow_name} flow"
        if sli == "latency":
            rationale = (
                f"Multi-window burn-rate on the latency SLO ("
                f"{(str(pct) + ' ') if pct else ''}<= {threshold_ms}ms, target {target}%, budget "
                f"{round(budget_frac * 100, 3)}%): {numerator} on {scope}."
            )
        else:
            rationale = (
                f"Multi-window error-budget burn-rate against SLO target {target}% "
                f"(budget {round(budget_frac * 100, 3)}%): {numerator} on {scope}."
            )
        docs.append(
            _doc(
                "Alert",
                f"{flow_name}-{sli}-burn-rate",
                {
                    "alertType": "burn-rate",
                    "sloRef": slo_ref,
                    "signalSource": "metric",
                    "severity": effective_severity("high", floor_tier),
                    "forFlow": flow_name,
                    "logFormatRef": None,
                    "expr": expr,
                    "rationale": rationale,
                    # Tool-neutral intent (adopted from resiliency-skills AlertIntent), on our envelope.
                    "class": "symptom",
                    "signal": {
                        "type": "metric",
                        "route": uri,
                        "metric": "http_server_requests_seconds",
                        "description": numerator,
                    },
                    "burnRate": _burn_rate_summary(slo_ref, sli, budget_frac),
                    "renderTargets": rendered_targets(expr),
                },
                [objective.evidence] + ([slo.evidence] if slo else []),
                "verified",
                confidence(Signal.DERIVED),  # computed from the SLO objective
                service,
                cross_refs=[
                    {"kind": "Flow", "name": flow_name, "relation": "alerts-on"},
                    {"kind": "SloSli", "name": slo_ref, "relation": "alerts-on"},
                ],
                unverified_against_live=True,  # burn-rate fires on live Prometheus metrics
            )
        )

    # --- Dashboard (RED overview for the top flow's route) ---
    # A generated monitoring dashboard (kind adopted from resiliency-skills, on our envelope):
    # Rate/Errors/Duration panels with deterministically generated Prometheus queries, scoped to the
    # flow's route. Lands needs-review (a suggested dashboard to verify) + unverifiedAgainstLive
    # (its queries fire on live metrics).
    if flow:
        d_uri = (flow.attrs.get("trigger") or {}).get("path")
        pct = objective.attrs.get("percentile") if objective else None
        d_ev = [objective.evidence] if objective else [flow.evidence]
        docs.append(
            _doc(
                "Dashboard",
                f"{service}-overview",
                {
                    "title": f"{service} — service overview (RED)",
                    "renderTarget": "prometheus",
                    "panels": red_panels(d_uri, percentile=pct),
                },
                d_ev,
                "needs-review",
                confidence(Signal.INFERRED),
                service,
                cross_refs=[{"kind": "Flow", "name": flow_name, "relation": "covers"}],
                unverified_against_live=True,
            )
        )

    # --- ScheduledJob (one per detected @Scheduled job; Tier-A, byte-grounded) ---
    for j in fs.of("job.scheduled"):
        a = j.attrs
        spec = {"name": a["name"], "jobType": a["jobType"]}
        if a.get("schedule"):
            spec["schedule"] = a["schedule"]
        if a.get("trigger"):
            spec["trigger"] = a["trigger"]
        if a.get("concurrency"):
            spec["concurrencyPolicy"] = a["concurrency"]
        docs.append(
            _doc("ScheduledJob", a["name"], spec, [j.evidence], "verified",
                 confidence(Signal.DIRECT), service)
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
                    # Every detected endpoint path, not just the first flow's trigger — the
                    # catalog projection prefixes each with `api:{service}`.
                    "providesApis": sorted({str(e.attrs.get("path") or "/")
                                            for e in fs.of("rest.endpoint")}),
                    "dependsOn": app.attrs.get("services", []),
                },
                [app.evidence],
                "verified",
                confidence(Signal.DIRECT),  # from the PCF manifest
                service,
            )
        )

    # --- P2 inventory kinds (TechStack, Deployment, Dependency, Interface, ConfigManagement) ---
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
