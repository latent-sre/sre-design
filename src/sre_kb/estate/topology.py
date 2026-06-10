"""Build a cross-service Topology and co-tenancy BlastRadius from multiple services'
facts. A resource bound by >1 service is shared — its failure spans all tenants."""

from __future__ import annotations

from sre_kb.inventory_signatures import is_broker, is_datastore
from sre_kb.synth.emit import emit
from sre_kb.util import slug

# Flow sinks carry the code-side target type; bindings carry the platform-side resource type.
_SINK_TYPE_FOR = {"datastore": "db", "broker": "kafka"}


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
            downstream = c.attrs.get("client", "downstream")
            nodes.setdefault(downstream, "external")
            edges.append({"from": name, "to": downstream, "relation": "calls"})

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
