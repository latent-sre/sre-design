"""P2 inventory kinds — deterministic roll-ups of facts we already collect:
TechStack, Deployment (infra+capacity), Dependency, Interface, DataStore,
ConfigManagement. Same envelope/validation machinery as the P1 kinds."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import FactSet
from sre_kb.scoring.confidence import Signal, confidence
from sre_kb.synth.emit import emit

_DATASTORE_HINTS = ("postgres", "mysql", "oracle", "mssql", "sqlserver", "db2", "mongo",
                    "redis", "cassandra", "sql", "db")
_BROKER_HINTS = ("kafka", "rabbit", "amqp", "jms", "mq", "pubsub")


def _is_datastore(name: str) -> bool:
    return any(h in name.lower() for h in _DATASTORE_HINTS)


def _is_broker(name: str) -> bool:
    return any(h in name.lower() for h in _BROKER_HINTS)


def inventory_docs(fs: FactSet, ctx: ScanContext, service: str) -> list[dict]:
    docs: list[dict] = []
    app = fs.first("pcf.app")
    framework = fs.first("tech.framework")
    has_cb = bool(fs.first("resiliency.circuitbreaker"))

    # --- TechStack ---
    if framework or app:
        deps = [f.attrs["name"] for f in fs.of("tech.dependency")]
        # Language/runtime come from a `tech.runtime` fact when a collector emits one (e.g. Python);
        # the JVM stacks don't, so they keep the historical java/jvm/maven defaults.
        rt = fs.first("tech.runtime")
        spec = {
            "languages": [rt.attrs["language"]] if rt else ["java"],
            "frameworks": [framework.attrs] if framework else [],
            "runtime": rt.attrs.get("runtime") if rt else "jvm",
            "buildTool": rt.attrs.get("buildTool") if rt else ("maven" if ctx.files("pom.xml") else "gradle"),
            "notableLibraries": deps[:20],
        }
        if app:
            spec["pcf"] = {"buildpacks": app.attrs.get("buildpacks", []), "stack": app.attrs.get("stack")}
        docs.append(emit("TechStack", service, spec, [framework.evidence] if framework else [app.evidence],
                         "verified", confidence(Signal.DIRECT), service))

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
    for sb in fs.of("pcf.service-binding"):
        name = sb.attrs["name"]
        dtype = "datastore" if _is_datastore(name) else "broker" if _is_broker(name) else "service-binding"
        docs.append(emit("Dependency", name, {
            "name": name,
            "type": dtype,
            "source": "pcf-service-binding",
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
        docs.append(emit("Interface", service, {
            "style": "rest+async" if (endpoints and channels) else ("rest" if endpoints else "async"),
            "endpoints": [
                {"method": e.attrs.get("method"), "path": e.attrs.get("path"),
                 "handler": e.attrs.get("handler"), "idempotent": None, "retrySafe": None}
                for e in endpoints
            ],
            "channels": [
                {"channel": c.attrs.get("channel"), "role": "producer", "broker": c.attrs.get("broker")}
                for c in channels
            ],
        }, ev, "verified", confidence(Signal.DIRECT), service))

    # --- DataStore (per datastore binding) ---
    repo = fs.first("db.repository")
    for sb in fs.of("pcf.service-binding"):
        name = sb.attrs["name"]
        if not _is_datastore(name):
            continue
        docs.append(emit("DataStore", name, {
            "engine": next((h for h in _DATASTORE_HINTS if h in name.lower()), "unknown"),
            "name": name,
            "accessedBy": [repo.attrs["name"]] if repo else [],
            "migrations": [],  # no Flyway/Liquibase detected
            "backup": "needs-review",
            "rpo": None,
            "rto": None,
            "sharedBy": [],
        }, [sb.evidence], "verified", confidence(Signal.DERIVED), service))

    # --- ConfigManagement ---
    config_facts = fs.of("config.slo", "config.client", "config.timelimiter", "config.actuator")
    if config_facts:
        profiles = (app.attrs.get("env") or {}).get("SPRING_PROFILES_ACTIVE") if app else None
        docs.append(emit("ConfigManagement", service, {
            "sources": ["application.yml", "pcf-manifest-env"],
            "profiles": [profiles] if profiles else [],
            "refreshScope": False,
            "properties": [f.attrs for f in config_facts],
        }, [config_facts[0].evidence], "verified", confidence(Signal.DIRECT), service))

    return docs
