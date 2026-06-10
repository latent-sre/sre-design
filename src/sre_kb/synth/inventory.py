"""P2 inventory kinds — deterministic roll-ups of facts we already collect:
TechStack, Deployment (infra+capacity), Dependency, Interface,
ConfigManagement. Same envelope/validation machinery as the P1 kinds.

S1: the former DataStore kind folded into Dependency (a datastore binding is a Dependency carrying
its `engine`); its infra fields (backup/RPO/RTO) are platform-DR an app team doesn't own (SCOPE §5)."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common.idempotency import MUTATING, scope_text
from sre_kb.collectors.common.openapi import normalize_path
from sre_kb.inventory_signatures import (
    StackSig,
    all_manifests,
    broker_kind,
    datastore_engine,
    is_broker,
    is_datastore,
    is_manifest_of,
    stack_for_manifests,
)
from sre_kb.models.facts import FactSet
from sre_kb.scoring.confidence import Signal, confidence
from sre_kb.signatures import fires
from sre_kb.synth.emit import emit


def _detect_stack(ctx: ScanContext) -> tuple[StackSig | None, str | None]:
    """The repo's primary tech stack from its manifest files (the data-driven breadth path), with the
    relpath of the manifest to cite. Used only as a fallback when no collector emitted a `tech.runtime`
    fact — e.g. a Node or Go service the AST collectors don't parse yet — so coverage widens without a
    new collector (HYBRID-PLAN §9.7 N5)."""
    present = {ctx.rel(p): p.name for p in ctx.files(*all_manifests())}
    stack = stack_for_manifests(present.values())
    if stack is None:
        return None, None
    rel = next((r for r, name in present.items() if is_manifest_of(stack, name)), None)
    return stack, rel


def inventory_docs(fs: FactSet, ctx: ScanContext, service: str) -> list[dict]:
    docs: list[dict] = []
    app = fs.first("pcf.app")
    framework = fs.first("tech.framework")
    has_cb = bool(fs.first("resiliency.circuitbreaker"))

    # --- TechStack ---
    # Language/runtime come from a `tech.runtime` fact when a collector emits one (e.g. Python); the
    # JVM stacks don't, so they keep the historical java/jvm/maven defaults. When no collector ran
    # (Node/Go), fall back to the declarative manifest stack so the roll-up still covers the repo.
    rt = fs.first("tech.runtime")
    stack, stack_rel = (None, None) if rt else _detect_stack(ctx)
    if framework or app or (stack and stack_rel):
        deps = [f.attrs["name"] for f in fs.of("tech.dependency")]
        spec = {
            "languages": [rt.attrs["language"]] if rt else ([stack.language] if stack else ["java"]),
            "frameworks": [framework.attrs] if framework else [],
            "runtime": rt.attrs.get("runtime") if rt else (stack.runtime if stack else "jvm"),
            "buildTool": (rt.attrs.get("buildTool") if rt
                          else stack.build_tool if stack
                          else ("maven" if ctx.files("pom.xml") else "gradle")),
            "notableLibraries": deps[:20],
        }
        if app:
            spec["pcf"] = {"buildpacks": app.attrs.get("buildpacks", []), "stack": app.attrs.get("stack")}
        # Cite the framework/app declaration when we have one; a manifest-only stack is DERIVED
        # (presence-based — the manifest declares the runtime, the framework isn't parsed).
        if framework:
            ev, sig = [framework.evidence], Signal.DIRECT
        elif app:
            ev, sig = [app.evidence], Signal.DIRECT
        else:
            ev, sig = [ctx.evidence(stack_rel, 1, 1, "inventory.stack")], Signal.DERIVED
        docs.append(emit("TechStack", service, spec, ev, "verified", confidence(sig), service))

    # --- Architecture (components / layers / patterns) ---
    comps: list[dict] = []
    layers: set[str] = set()
    patterns: list[str] = []
    seen: set[str] = set()

    def _add_comp(name: str, ctype: str, symbol: str) -> None:
        if symbol in seen:
            return
        seen.add(symbol)
        comps.append({"name": name, "type": ctype, "symbol": symbol})
        layers.add(ctype)

    for e in fs.of("rest.endpoint"):
        cls = e.attrs["handler"].split("#")[0]
        _add_comp(cls.split(".")[-1], "web", cls)
    cb = fs.first("resiliency.circuitbreaker")
    if cb:
        cls = (cb.attrs.get("targetSymbol") or "client").split("#")[0]
        _add_comp(cls.split(".")[-1], "client", cls)
        patterns.append("circuit-breaker")
    if fs.first("resiliency.fallback"):
        patterns.append("fallback")
    repo_fact = fs.first("db.repository")
    if repo_fact:
        _add_comp(repo_fact.attrs["name"], "persistence", repo_fact.attrs["name"])
        patterns.append("repository")
    pub = fs.first("message.egress")
    if pub:
        cls = pub.attrs.get("class", "events")
        _add_comp(cls.split(".")[-1], "messaging", cls)
        patterns.append("async-messaging")
    if comps:
        endpoints = fs.of("rest.endpoint")
        arch_ev = [endpoints[0].evidence] if endpoints else ([cb.evidence] if cb else [])
        docs.append(emit("Architecture", service, {
            "components": comps, "layers": sorted(layers),
            "patterns": patterns, "styleTags": ["layered"],
        }, arch_ev, "verified", confidence(Signal.DERIVED), service))  # composed from components

    # --- Deployment (infra + capacity) ---
    if app:
        a = app.attrs
        docs.append(emit("Deployment", service, {
            "hosting": "PCF",
            "instances": a.get("instances"),
            "memory": a.get("memory"),
            "disk": a.get("disk"),
            "routes": a.get("routes", []),
            "services": a.get("services", []),
            "stack": a.get("stack"),
            "buildpacks": a.get("buildpacks", []),
            "healthCheck": a.get("healthCheck", {}),
            "profiles": (a.get("env") or {}).get("SPRING_PROFILES_ACTIVE"),
        }, [app.evidence], "verified", confidence(Signal.DIRECT), service))

    # --- Dependency (runtime service deps: bindings + downstream HTTP) ---
    # S1: a datastore/broker binding folds into Dependency (app binds X), carrying its `engine` — the
    # former DataStore kind's infra fields (backup/RPO/RTO) are platform-DR concerns an app team
    # doesn't own (SCOPE §5).
    for sb in fs.of("pcf.service-binding"):
        name = sb.attrs["name"]
        dtype = "datastore" if is_datastore(name) else "broker" if is_broker(name) else "service-binding"
        docs.append(emit("Dependency", name, {
            "name": name,
            "type": dtype,
            "source": "pcf-service-binding",
            "engine": datastore_engine(name) if dtype == "datastore" else (
                broker_kind(name) if dtype == "broker" else None),
            "criticality": "critical",
        }, [sb.evidence], "verified", confidence(Signal.DIRECT), service))
    for c in fs.of("config.client"):
        cname = c.attrs.get("client", "downstream")
        docs.append(emit("Dependency", f"{cname}-http", {
            "name": cname,
            "type": "http",
            "source": "config",
            "baseUrl": c.attrs.get("baseUrl"),
            "criticality": "contained" if has_cb else "critical",
        }, [c.evidence], "verified", confidence(Signal.DERIVED), service))

    # --- Interface (REST + async unified) ---
    endpoints = fs.of("rest.endpoint")
    channels = fs.of("message.egress")
    if endpoints or channels:
        ev = [endpoints[0].evidence] if endpoints else [channels[0].evidence]
        # API-contract drift (#7): join detected endpoints to an ingested OpenAPI spec, if present.
        spec_eps = fs.of("api.spec.endpoint")
        spec_keys = {(s.attrs["method"], s.attrs["normPath"]) for s in spec_eps}
        detected_keys = {(e.attrs.get("method"), normalize_path(str(e.attrs.get("path", "/"))))
                         for e in endpoints}

        def _endpoint(e):
            # Safe methods are idempotent by HTTP semantics; mutating ones iff an idempotency
            # guard fires in the handler's scope (the same Tier-A signature the gap collector
            # uses, so Interface and `missing-idempotency` gaps can never disagree).
            method = e.attrs.get("method")
            if method in {"GET", "HEAD", "OPTIONS"}:
                idem = True
            elif method in MUTATING:
                idem = fires("idempotency",
                             scope_text(ctx, e.evidence.path, e.evidence.lines.start))
            else:
                idem = None
            ep = {"method": method, "path": e.attrs.get("path"),
                  "handler": e.attrs.get("handler"), "idempotent": idem, "retrySafe": idem}
            if spec_eps:  # only assert documented/undocumented when a spec was ingested
                key = (e.attrs.get("method"), normalize_path(str(e.attrs.get("path", "/"))))
                ep["documented"] = key in spec_keys
            return ep

        interface_spec = {
            "style": "rest+async" if (endpoints and channels) else ("rest" if endpoints else "async"),
            "endpoints": [_endpoint(e) for e in endpoints],
            "channels": [
                {"channel": c.attrs.get("channel"), "role": "producer", "broker": c.attrs.get("broker")}
                for c in channels
            ],
        }
        if spec_eps:
            first = spec_eps[0].attrs
            contract = {
                "source": first.get("source"),
                "specPath": first.get("specPath"),
                "version": first.get("specVersion"),
                "documented": sum(1 for k in detected_keys if k in spec_keys),
                "undocumented": sorted(f"{m} {p}" for (m, p) in detected_keys - spec_keys),
                "specOnly": sorted(f"{s.attrs['method']} {s.attrs['path']}"
                                   for s in spec_eps
                                   if (s.attrs["method"], s.attrs["normPath"]) not in detected_keys),
            }
            ev = ev + [spec_eps[0].evidence]
            # Baseline diff (#7 versioning): deterministic, byte-grounded breaking-change facts vs a
            # committed `.sre/api-baseline/` spec. Self-gating — absent unless a baseline was diffed.
            changes = fs.of("api.contract.change")
            version_policy = fs.first("api.contract.versionPolicy")
            if changes or version_policy:
                contract["baselineVersion"] = (changes[0].attrs.get("baselineVersion")
                                               if changes else version_policy.attrs.get("baselineVersion"))
                contract["changes"] = [
                    {"changeType": c.attrs["changeType"], "ref": c.attrs["ref"],
                     "breaking": c.attrs["breaking"], "detail": c.attrs.get("detail")}
                    for c in sorted(changes, key=lambda c: (not c.attrs["breaking"], c.attrs["ref"]))
                ]
                if version_policy:
                    vp = version_policy.attrs
                    contract["versionPolicy"] = {
                        "ok": vp["ok"], "breakingChanges": vp["breakingChanges"],
                        "majorBumped": vp["majorBumped"], "detail": vp.get("detail"),
                    }
                    ev = ev + [version_policy.evidence]
            interface_spec["contract"] = contract
        docs.append(emit("Interface", service, interface_spec, ev, "verified",
                         confidence(Signal.DIRECT), service))

    # --- Topology (single-service): the app-centric graph the estate run merges; emitting it
    # per run means one service's bindings/downstreams are drawable without an estate sweep ---
    bindings = fs.of("pcf.service-binding")
    clients = fs.of("config.client")
    if bindings or clients:
        topo_nodes: list[dict] = [{"type": "service", "name": service}]
        topo_edges: list[dict] = []
        seen_nodes = {service}
        for sb in bindings:
            res = sb.attrs["name"]
            if res not in seen_nodes:
                seen_nodes.add(res)
                topo_nodes.append({
                    "type": "datastore" if is_datastore(res) else "broker" if is_broker(res) else "resource",
                    "name": res,
                })
            topo_edges.append({"from": service, "to": res, "relation": "binds"})
        for c in clients:
            downstream = c.attrs.get("client", "downstream")
            if downstream not in seen_nodes:
                seen_nodes.add(downstream)
                topo_nodes.append({"type": "external", "name": downstream})
            topo_edges.append({"from": service, "to": downstream, "relation": "calls"})
        topo_ev = [(bindings[0] if bindings else clients[0]).evidence]
        docs.append(emit("Topology", service, {
            "nodes": topo_nodes,
            "edges": topo_edges,
            "pcfSpaces": [],
        }, topo_ev, "verified", confidence(Signal.DIRECT), service))

    # --- ConfigManagement ---
    config_facts = fs.of("config.slo", "config.client", "config.timelimiter", "config.actuator")
    if config_facts:
        profiles = (app.attrs.get("env") or {}).get("SPRING_PROFILES_ACTIVE") if app else None
        # Sources are the files the config facts actually cite, plus the manifest env block
        # when one exists — not a hardcoded list.
        sources = sorted({f.evidence.path for f in config_facts})
        if app and app.attrs.get("env"):
            sources.append("pcf-manifest-env")
        docs.append(emit("ConfigManagement", service, {
            "sources": sources,
            "profiles": [profiles] if profiles else [],
            "refreshScope": bool(fs.first("config.refreshscope")),
            "properties": [f.attrs for f in config_facts],
        }, [config_facts[0].evidence], "verified", confidence(Signal.DIRECT), service))

    # --- FeatureFlag (coverage matrix #15: config blocks / @ConditionalOnProperty / flag-SDK calls) ---
    for ff in fs.of("feature.flag"):
        a = ff.attrs
        docs.append(emit("FeatureFlag", a["name"], {
            "name": a["name"],
            "provider": a.get("provider"),
            "defaultState": a.get("defaultState", "unknown"),
            "killSwitch": a.get("killSwitch", False),
        }, [ff.evidence], "verified", confidence(Signal.DIRECT), service))

    return docs
