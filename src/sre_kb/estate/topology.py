"""Build a cross-service Topology and co-tenancy BlastRadius from multiple services'
facts. A resource bound by >1 service is shared — its failure spans all tenants."""

from __future__ import annotations

from sre_kb.synth.emit import emit
from sre_kb.synth.inventory import _is_broker, _is_datastore


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
            nodes[res] = "datastore" if _is_datastore(res) else "broker" if _is_broker(res) else "resource"
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
                    "impactedFlows": [],
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
