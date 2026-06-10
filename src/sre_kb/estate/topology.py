"""Build a cross-service Topology and co-tenancy BlastRadius from multiple services'
facts. A resource bound by >1 service is shared — its failure spans all tenants."""

from __future__ import annotations

import fnmatch
import re

from sre_kb.inventory_signatures import is_broker, is_datastore
from sre_kb.synth.emit import emit
from sre_kb.util import slug

_IP_HOST = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# Flow sinks carry the code-side target type; bindings carry the platform-side resource type.
_SINK_TYPE_FOR = {"datastore": "db", "broker": "kafka"}

# §5.7: how many caller hops the impact fold walks (A→B→C reach without unbounded cycles).
_TRANSITIVE_DEPTH = 3


def _transitive_callers(direct: set[str], callers_of: dict[str, set[str]]) -> set[str]:
    """Services that degrade because something they call is impacted: walk resolved `calls`
    edges against their direction from the directly-impacted set, bounded depth. Returns only
    the indirect reach (the input set excluded)."""
    reach, frontier = set(direct), set(direct)
    for _ in range(_TRANSITIVE_DEPTH):
        nxt = {c for s in frontier for c in callers_of.get(s, ())} - reach
        if not nxt:
            break
        reach |= nxt
        frontier = nxt
    return reach - direct


def _internal_libs(fs, patterns: tuple[str, ...]) -> dict[str, str | None]:
    """lib name -> pinned version (or None) for the `tech.dependency` facts matching the
    internal-namespace allowlist. Patterns are shell globs matched against the dependency name,
    its group, and `group:name` — so `com.acme*` catches Maven coordinates and `@acme/*`
    catches scoped npm packages."""
    out: dict[str, str | None] = {}
    for f in fs.of("tech.dependency"):
        name = f.attrs["name"]
        group = f.attrs.get("group")
        keys = [name] + ([group, f"{group}:{name}"] if group else [])
        if any(fnmatch.fnmatchcase(k, p) for k in keys for p in patterns):
            out[name] = f.attrs.get("version")
    return out


def library_version_skew(services: list[dict],
                         internal_namespaces: tuple[str, ...]) -> list[dict]:
    """Version-skew findings: an internal library pinned at different versions by different
    services means a change to it blasts into all of them — and they disagree about which
    version of it they share."""
    by_lib: dict[str, dict[str, str | None]] = {}
    for s in services:
        for lib, version in _internal_libs(s["fs"], internal_namespaces).items():
            by_lib.setdefault(lib, {})[s["service"]] = version
    findings: list[dict] = []
    for lib, by_svc in sorted(by_lib.items()):
        pinned = {v for v in by_svc.values() if v}
        if len(by_svc) >= 2 and len(pinned) >= 2:
            findings.append({
                "type": "library-version-skew",
                "severity": "medium",
                "library": lib,
                "versions": dict(sorted(by_svc.items())),
                "detail": (f"{lib} is pinned at {len(pinned)} different versions across "
                           f"{len(by_svc)} services — a library change blasts into all of "
                           "them, and the skew means they already disagree about its behavior."),
            })
    return findings


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


def _route_owners(services: list[dict]) -> dict[str, str]:
    """hostname -> owning scanned service, from each service's PCF route declarations."""
    out: dict[str, str] = {}
    for s in services:
        app = s["fs"].first("pcf.app")
        for route in (app.attrs.get("routes") or []) if app else []:
            host = _host(route)
            if host:
                out[host] = s["service"]
    return out


def ambiguous_call_edges(services: list[dict]) -> list[dict]:
    """Cross-repo edge candidates the deterministic join must NOT guess (§3.2/§5.6): an
    IP-literal baseUrl (it could be anything) and an unmatched hostname whose first label
    matches a scanned service's name (an alias suspicion). Each becomes a confirm-worklist
    item and an advisory finding — never an invented edge; the graph stays downgrade-only
    honest."""
    route_owner = _route_owners(services)
    by_slug = {slug(s["service"]): s["service"] for s in services}
    items: list[dict] = []
    for s in services:
        name = s["service"]
        for c in s["fs"].of("config.client"):
            base_url = c.attrs.get("baseUrl")
            host = _host(base_url)
            if not host or host in route_owner:
                continue  # resolved (or undeclarable) — not ambiguous
            candidate = (by_slug.get(slug(host.split(".", 1)[0]))
                         or by_slug.get(slug(str(c.attrs.get("client")))))
            if candidate == name:
                candidate = None
            reason = ("ip-literal" if _IP_HOST.match(host)
                      else "alias-suspect" if candidate
                      else None)
            if reason is None:
                continue  # a plain external hostname is the external node, as before
            ev = c.evidence
            items.append({
                "claimId": f"edge:{name}:{slug(str(c.attrs.get('client')))}",
                "from": name,
                "client": c.attrs.get("client"),
                "baseUrl": base_url,
                "reason": reason,
                "candidate": candidate if reason == "alias-suspect" else None,
                "evidence": f"{ev.path}:{ev.lines.start}",
                "prompt": (
                    f"Service `{name}` declares HTTP client `{c.attrs.get('client')}` with "
                    f"baseUrl `{base_url}` ({ev.path}:{ev.lines.start}). The engine could not "
                    "resolve this hostname to any scanned service's route"
                    + (f"; its first label resembles scanned service `{candidate}`"
                       if candidate else " and it is an IP literal")
                    + ". Reply `affirm` if it is genuinely external, or `dispute` followed by "
                    "the scanned service name it actually targets."
                ),
            })
    return items


def _path_hits(changed: str, consumer: str) -> bool:
    """Does a changed endpoint path (normPath, `{}` templates) match a consumer-side URL
    literal? Conservative by design: an equal-length segment match where `{}` matches any
    one segment, or the classic string-concat prefix (`"/orders/" + id` — the literal ends
    with `/` and covers everything but a final `{}` segment). Anything fuzzier would invent
    impact."""
    changed_segs = [s for s in changed.split("/") if s]
    literal = consumer.split("?", 1)[0]
    consumer_segs = [s for s in literal.split("/") if s]
    if literal.endswith("/") and consumer_segs:
        # `"/tenants/{x}/orders/" + id` — present segments still match `{}` wildcards.
        return (len(changed_segs) == len(consumer_segs) + 1
                and changed_segs[-1] == "{}"
                and all(c == "{}" or c == u for c, u in zip(changed_segs, consumer_segs)))
    return len(changed_segs) == len(consumer_segs) and all(
        c == "{}" or c == u for c, u in zip(changed_segs, consumer_segs))


def _consumer_paths(fs, provider: str, route_owner: dict[str, str],
                    sole_provider: str | None) -> set[str]:
    """The egress URL paths a consumer's code aims at `provider`: absolute URLs attributed by
    their hostname, relative paths only when `provider` is the consumer's sole resolved
    callee (the same sole-candidate rule the lossy-sink attribution uses)."""
    out: set[str] = set()
    for f in fs.of("http.egress"):
        url = f.attrs.get("url")
        if not url:
            continue
        if url.startswith(("http://", "https://")):
            if route_owner.get(_host(url)) != provider:
                continue
            rest = url.split("://", 1)[1]
            path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
        elif sole_provider == provider:
            path = url
        else:
            continue
        out.add(path)
    return out


def contract_change_blast(services: list[dict], edges: list[dict]) -> list[dict]:
    """Estate-level blast radius for breaking API changes (§5.5): a provider whose baseline
    diff produced breaking `api.contract.change` facts impacts every scanned consumer with a
    resolved `calls` edge to it — 'this change breaks services X, Y', not a single-repo note.
    When consumers' code carries literal egress URLs, the subset whose paths hit a changed
    endpoint is additionally labeled `preciselyImpacted`."""
    names = {s["service"] for s in services}
    fs_by_service = {s["service"]: s["fs"] for s in services}
    route_owner = _route_owners(services)
    consumers_of: dict[str, set[str]] = {}
    providers_of: dict[str, set[str]] = {}
    for e in edges:
        if e.get("relation") == "calls" and e.get("from") in names and e.get("to") in names:
            consumers_of.setdefault(e["to"], set()).add(e["from"])
            providers_of.setdefault(e["from"], set()).add(e["to"])
    findings: list[dict] = []
    for s in sorted(services, key=lambda s: s["service"]):
        provider = s["service"]
        breaking = [f for f in s["fs"].of("api.contract.change") if f.attrs.get("breaking")]
        impacted = sorted(consumers_of.get(provider, ()))
        if not (breaking and impacted):
            continue
        changes = sorted(f"{f.attrs['changeType']} {f.attrs['ref']}" for f in breaking)
        changed_paths = {str(f.attrs["ref"]).split(" ", 1)[1] for f in breaking
                         if " " in str(f.attrs["ref"])}
        precise = []
        for consumer in impacted:
            sole = next(iter(providers_of[consumer])) if len(providers_of.get(consumer, ())) == 1 else None
            paths = _consumer_paths(fs_by_service[consumer], provider, route_owner, sole)
            if any(_path_hits(ch, p) for ch in changed_paths for p in paths):
                precise.append(consumer)
        finding = {
            "type": "api-breaking-change-blast",
            "severity": "high",
            "provider": provider,
            "impactedServices": impacted,
            "changes": changes,
            "detail": (f"{provider} has {len(breaking)} breaking API change(s) vs its "
                       f"committed baseline ({'; '.join(changes)}) — scanned consumers "
                       f"impacted: {', '.join(impacted)}."),
        }
        if precise:
            finding["preciselyImpacted"] = precise
            finding["detail"] += (f" Code-level path evidence confirms the hit for: "
                                  f"{', '.join(precise)}.")
        findings.append(finding)
    return findings


def build_estate(services: list[dict],
                 internal_namespaces: tuple[str, ...] = ()) -> list[dict]:
    """services: [{"service": name, "ctx": ScanContext, "fs": FactSet}]. `internal_namespaces`
    is the shared-library allowlist (config `estate.internal_namespaces`); empty = no library
    lineage."""
    docs: list[dict] = []
    nodes: dict[str, str] = {}
    edges: list[dict] = []
    topo_evidence = []
    owners: dict[str, dict] = {}  # resource -> {service: Evidence}

    # Pass 1: each service's PCF route hostnames, so a config-declared baseUrl pointing at
    # another scanned service resolves to a real service->service edge, not an external node.
    # A provider with an ingested OpenAPI spec backs its resolved edges with that contract.
    route_owner = _route_owners(services)
    has_contract = {s["service"]: bool(s["fs"].of("api.spec.endpoint")) for s in services}

    for s in services:
        name = s["service"]
        fs = s["fs"]
        # A scanned repo whose stack is a frontend framework renders as `frontend`: the SPA
        # connects to its API repo through the same baseUrl join, but the drawing should say
        # which side the user sits on.
        nodes[name] = "frontend" if fs.first("tech.frontend") else "service"
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
                edge = {"from": name, "to": resolved, "relation": "calls"}
                if has_contract.get(resolved):
                    edge["contract"] = "openapi"  # the edge is backed by the provider's spec
                edges.append(edge)
            else:
                downstream = c.attrs.get("client", "downstream")
                if slug(str(downstream)) in {slug(s["service"]) for s in services}:
                    # The client KEY collides with a scanned service (slug-compared, the same
                    # normalization ambiguous_call_edges uses) but its baseUrl did not resolve
                    # to that service's routes: drawing the edge — or a near-name external
                    # node beside the real service — would be a guess. It stays off the
                    # graph; ambiguous_call_edges routes it to confirmation.
                    continue
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
        # Shared-library lineage: internal dependencies (allowlisted namespaces) join across
        # repos, so "which services does a change to this library blast into?" reads off the graph.
        for lib in _internal_libs(fs, internal_namespaces):
            nodes.setdefault(lib, "library")
            edges.append({"from": name, "to": lib, "relation": "uses-library"})

    deduped: list[dict] = []
    seen_edges: set[tuple] = set()
    for e in edges:
        key = (e["from"], e["to"], e.get("relation"))
        if key not in seen_edges:
            seen_edges.add(key)
            deduped.append(e)
    edges = deduped

    # §4.3: org/space from each service's cf-env snapshot — the grouping that makes blast
    # radius legible to an app team ("everything in acme/prod degrades together").
    by_space: dict[tuple, list[str]] = {}
    for s in services:
        sp = s["fs"].first("pcf.space")
        if sp and (sp.attrs.get("organization") or sp.attrs.get("space")):
            key = (sp.attrs.get("organization"), sp.attrs.get("space"))
            by_space.setdefault(key, []).append(s["service"])
            topo_evidence.append(sp.evidence)
    pcf_spaces = [{"organization": org, "space": space, "services": sorted(svcs)}
                  for (org, space), svcs in sorted(by_space.items(), key=str)]

    docs.append(
        emit(
            "Topology",
            "estate",
            {
                "nodes": [{"type": t, "name": n} for n, t in nodes.items()],
                "edges": edges,
                "pcfSpaces": pcf_spaces,
            },
            topo_evidence,
            "verified",
            0.85,
            "estate",
        )
    )

    # §5.7: resolved calls edges, reversed — who degrades when a service is impacted.
    svc_names = {s["service"] for s in services}
    callers_of: dict[str, set[str]] = {}
    for e in edges:
        if e.get("relation") == "calls" and e["from"] in svc_names and e["to"] in svc_names:
            callers_of.setdefault(e["to"], set()).add(e["from"])

    fs_by_service = {s["service"]: s["fs"] for s in services}
    for res, by_service in sorted(owners.items()):
        if len(by_service) < 2:
            continue  # not shared -> not co-tenancy
        ntype = nodes.get(res, "resource")
        indirect = sorted(_transitive_callers(set(by_service), callers_of))
        spec = {
            "node": {"type": ntype, "name": res},
            "impactedFlows": _impacted_flows(res, ntype, by_service, fs_by_service),
            "impactedServices": sorted(set(by_service) | set(indirect)),
            "coTenancy": [{"sharedBy": sorted(by_service.keys())}],
            "stateful": {"dataLossRisk": ntype == "datastore"},
            "dependencyCriticality": "critical",
            "severityHint": "critical",
        }
        if indirect:
            spec["indirectServices"] = indirect
        docs.append(
            emit(
                "BlastRadius",
                f"{res}-cotenancy",
                spec,
                list(by_service.values()),
                "verified",
                0.8,
                "estate",
            )
        )
    return docs
