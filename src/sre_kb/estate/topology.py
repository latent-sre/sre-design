"""Build a cross-service Topology and co-tenancy BlastRadius from multiple services'
facts. A resource bound by >1 service is shared — its failure spans all tenants."""

from __future__ import annotations

from sre_kb.inventory_signatures import is_broker, is_datastore
from sre_kb.synth.emit import emit
from sre_kb.util import slug

# Flow sinks carry the code-side target type; bindings carry the platform-side resource type.
_SINK_TYPE_FOR = {"datastore": "db", "broker": "kafka"}


def _host(value: object) -> str:
    """The bare hostname of a route or baseUrl: scheme, path, and port stripped, lowercased.
    Both sides of the route<->baseUrl join MUST normalize identically — Spring config commonly
    omits the scheme (`base-url: callee.apps.internal`) and an internal route can carry a port
    (`callee.apps.internal:8080`); either asymmetry silently breaks the join."""
    rest = str(value or "").split("://", 1)[-1]
    return rest.split("/", 1)[0].rsplit(":", 1)[0].strip().lower()


def _impacted_flows(res: str, ntype: str, owners: dict, fs_by_service: dict) -> list[str]:
    """Flows (as `service/flow`) whose sinks hit the shared resource `res`. A sink names the
    code-side target (repository class, channel), not the binding, so attribution is: a direct
    slug match, or — when the service binds exactly one resource of that type — any sink of the
    matching kind (the binding the write can only be going to)."""
    impacted: list[str] = []
    res_slug = slug(res)
    sink_type = _SINK_TYPE_FOR.get(ntype)
    for svc in sorted(owners):
        fs = fs_by_service[svc]
        sole_of_type = sum(
            1 for sb in fs.of("pcf.service-binding")
            if (is_datastore(sb.attrs["name"]) and ntype == "datastore")
            or (is_broker(sb.attrs["name"]) and ntype == "broker")
        ) == 1
        for ff in fs.of("flow.flow"):
            for sink in ff.attrs.get("sinks", []):
                direct = slug(str(sink.get("target"))) == res_slug
                by_kind = sole_of_type and sink_type is not None and sink.get("type") == sink_type
                if direct or by_kind:
                    impacted.append(f"{svc}/{ff.attrs['name']}")
                    break
    return impacted


def build_estate(services: list[dict]) -> list[dict]:
    """services: [{"service": name, "ctx": ScanContext, "fs": FactSet}]."""
    docs: list[dict] = []
    nodes: dict[str, str] = {}
    edges: list[dict] = []
    topo_evidence = []
    owners: dict[str, dict] = {}  # resource -> {service: Evidence}

    # Pass 1: each service's PCF route hostnames, so a config-declared baseUrl pointing at
    # another scanned service resolves to a real service->service edge, not an external node.
    route_owner: dict[str, str] = {}
    for s in services:
        app = s["fs"].first("pcf.app")
        for route in (app.attrs.get("routes") or []) if app else []:
            host = _host(route)
            if host:
                route_owner[host] = s["service"]

    for s in services:
        name = s["service"]
        fs = s["fs"]
        nodes[name] = "service"
        app = fs.first("pcf.app")
        if app:
            topo_evidence.append(app.evidence)
        for sb in fs.of("pcf.service-binding"):
            res = sb.attrs["name"]
            nodes[res] = "datastore" if is_datastore(res) else "broker" if is_broker(res) else "resource"
            edges.append({"from": name, "to": res, "relation": "binds"})
            owners.setdefault(res, {})[name] = sb.evidence
        for c in fs.of("config.client"):
            resolved = route_owner.get(_host(c.attrs.get("baseUrl")))
            if resolved and resolved != name:
                edges.append({"from": name, "to": resolved, "relation": "calls"})
            else:
                downstream = c.attrs.get("client", "downstream")
                nodes.setdefault(downstream, "external")
                edges.append({"from": name, "to": downstream, "relation": "calls"})
        # Messaging topics join across repos: a channel one service publishes and another
        # consumes is a shared-fate edge the binding-only view misses.
        for pub in fs.of("message.egress"):
            channel = pub.attrs.get("channel")
            if channel:
                nodes.setdefault(channel, "topic")
                edges.append({"from": name, "to": channel, "relation": "publishes"})
        for con in fs.of("message.consumer"):
            channel = con.attrs.get("channel")
            if channel:
                nodes.setdefault(channel, "topic")
                edges.append({"from": channel, "to": name, "relation": "consumes"})

    deduped: list[dict] = []
    seen_edges: set[tuple] = set()
    for e in edges:
        key = (e["from"], e["to"], e.get("relation"))
        if key not in seen_edges:
            seen_edges.add(key)
            deduped.append(e)
    edges = deduped

    docs.append(
        emit(
            "Topology",
            "estate",
            {
                "nodes": [{"type": t, "name": n} for n, t in nodes.items()],
                "edges": edges,
                "pcfSpaces": [],
            },
            topo_evidence,
            "verified",
            0.85,
            "estate",
        )
    )

    fs_by_service = {s["service"]: s["fs"] for s in services}
    for res, by_service in sorted(owners.items()):
        if len(by_service) < 2:
            continue  # not shared -> not co-tenancy
        ntype = nodes.get(res, "resource")
        docs.append(
            emit(
                "BlastRadius",
                f"{res}-cotenancy",
                {
                    "node": {"type": ntype, "name": res},
                    "impactedFlows": _impacted_flows(res, ntype, by_service, fs_by_service),
                    "impactedServices": sorted(by_service.keys()),
                    "coTenancy": [{"sharedBy": sorted(by_service.keys())}],
                    "stateful": {"dataLossRisk": ntype == "datastore"},
                    "dependencyCriticality": "critical",
                    "severityHint": "critical",
                },
                list(by_service.values()),
                "verified",
                0.8,
                "estate",
            )
        )
    return docs
