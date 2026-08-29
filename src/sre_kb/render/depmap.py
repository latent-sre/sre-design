"""Per-service upstream/downstream dependency maps, in plain English.

Two projections over facts the KB already validated — no new joins are guessed here:

  * `dependency_map_markdown` — single-service run: the service's downstream dependencies
    (bound resources, called services, published topics) with each one's failure behavior in
    plain words, plus the honest single-repo upstream view (entry points + consumed topics;
    a lone repository cannot see its callers — the estate run resolves those).
  * `estate_dependency_map_markdown` — estate run: both directions resolved across every
    scanned service (who calls whom, who consumes whose topics, who shares whose resources),
    from the estate Topology/BlastRadius artifacts.

Attribution follows the engine's existing rules: flow failure modes attach to a bound
resource only via a direct name match or the sole-binding-of-type rule (the same rule the
estate impact join uses) — ambiguity renders nothing rather than a guess.
"""

from __future__ import annotations

from sre_kb.render.plain import failure_sentence
from sre_kb.render.templating import inline as _inline
from sre_kb.util import slug

GENERATED = "<!-- GENERATED from SRE KB — edit the KB, not this file. -->"

# Flow sink types -> the topology node type their writes can only be going to (the estate
# `_SINK_TYPE_FOR` mapping, docs-side).
_NODE_TYPE_FOR_SINK = {"datastore": "db", "broker": "kafka"}


def _of_kind(docs: list[dict], kind: str) -> list[dict]:
    return [d for d in docs if d.get("kind") == kind]


def _svc_topology(service: str, docs: list[dict]) -> dict | None:
    return next(
        (d for d in _of_kind(docs, "Topology") if (d.get("metadata") or {}).get("name") == service),
        None,
    )


def _failure_lines_by_target(docs: list[dict]) -> dict[str, list[str]]:
    """slugged sink target -> plain-English failure sentences, from every Flow's paired
    steps/sinks (the index-parallel guard the diagram renderer uses)."""
    out: dict[str, list[str]] = {}
    for f in _of_kind(docs, "Flow"):
        spec = f.get("spec", {})
        steps, sinks = spec.get("steps", []), spec.get("sinks", [])
        if len(steps) != len(sinks):
            continue
        for step, sink in zip(steps, sinks):
            target = slug(str((sink or {}).get("target")))
            for fm in step.get("failureModes", []):
                line = failure_sentence(fm)
                if line not in out.setdefault(target, []):
                    out[target].append(line)
    return out


def _sole_of_type(nodes: list[dict], ntype: str) -> str | None:
    named = [n["name"] for n in nodes if n.get("type") == ntype]
    return named[0] if len(named) == 1 else None


def _attributed_failures(node: dict, docs: list[dict], topo_nodes: list[dict],
                         by_target: dict[str, list[str]]) -> list[str]:
    """Failure sentences for a topology node: direct slug match on the sink target, else the
    sole-binding-of-type rule (a db sink can only be writing to the only bound datastore)."""
    direct = by_target.get(slug(node["name"]))
    if direct:
        return direct
    sink_type = _NODE_TYPE_FOR_SINK.get(node.get("type", ""))
    if sink_type and node["name"] == _sole_of_type(topo_nodes, node["type"]):
        # Every sink of the matching kind can only be going to this node.
        out: list[str] = []
        for f in _of_kind(docs, "Flow"):
            spec = f.get("spec", {})
            steps, sinks = spec.get("steps", []), spec.get("sinks", [])
            if len(steps) != len(sinks):
                continue
            for step, sink in zip(steps, sinks):
                if (sink or {}).get("type") == sink_type:
                    for fm in step.get("failureModes", []):
                        line = failure_sentence(fm)
                        if line not in out:
                            out.append(line)
        return out
    return []


def _blast_line(name: str, docs: list[dict]) -> str | None:
    """One plain sentence from the node's BlastRadius, when one exists."""
    br = next((d for d in _of_kind(docs, "BlastRadius")
               if (d.get("metadata") or {}).get("name") == slug(name)), None)
    if br is None:
        return None
    spec = br.get("spec", {})
    flows = ", ".join(f"`{_inline(f)}`" for f in spec.get("impactedFlows", []))
    bits = []
    if flows:
        bits.append(f"breaks {flows}")
    if (spec.get("stateful") or {}).get("dataLossRisk"):
        bits.append("**loses data** (no replay)")
    if spec.get("containment"):
        bits.append("contained by " + ", ".join(
            f"`{_inline(c.get('name'))}`" for c in spec["containment"]))
    else:
        bits.append("no containment — failures propagate")
    return "; ".join(bits) + f" (severity hint: {_inline(spec.get('severityHint', '-'))})."


_RELATION_PHRASE = {
    "binds": "bound platform service",
    "calls": "HTTP call",
    "publishes": "publishes events to",
    "consumes": "consumes events from",
    "uses-library": "shared internal library",
}


def dependency_map_markdown(service: str, docs: list[dict]) -> str:
    """The single-service upstream/downstream map (see module docstring)."""
    topo = _svc_topology(service, docs)
    nodes = {n["name"]: n for n in (topo.get("spec", {}).get("nodes", []) if topo else [])}
    edges = topo.get("spec", {}).get("edges", []) if topo else []
    by_target = _failure_lines_by_target(docs)
    topo_nodes = list(nodes.values())

    svc = _inline(service)
    lines = [
        GENERATED,
        f"# {svc} — dependency map",
        "",
        f"What `{svc}` needs to work (downstream), and what this repository can honestly",
        "say about who needs it (upstream). Generated from code — verify against live state.",
        "",
        f"## Downstream — what `{svc}` depends on",
        "",
    ]
    rows = [e for e in edges if e.get("from") == service and e.get("to") in nodes]
    if rows:
        lines += ["| Dependency | Kind | Relationship | If it fails (plain English) |",
                  "|---|---|---|---|"]
        for e in rows:
            node = nodes[e["to"]]
            failures = _attributed_failures(node, docs, topo_nodes, by_target)
            blast = _blast_line(node["name"], docs)
            plain = " ".join(failures) if failures else ""
            if blast:
                plain = (plain + " " if plain else "") + blast
            lines.append(
                f"| `{_inline(node['name'])}` | {_inline(node.get('type', '-'))} "
                f"| {_RELATION_PHRASE.get(e.get('relation', ''), _inline(e.get('relation', '-')))} "
                f"| {plain or '(no failure modes detected in code)'} |"
            )
    else:
        lines.append("No downstream dependencies were detected in code.")
    lines += ["", f"## Upstream — who depends on `{svc}`", ""]

    apis = sorted({str(p) for d in _of_kind(docs, "ServiceCatalogEntry")
                   for p in d.get("spec", {}).get("providesApis", [])})
    if apis:
        lines.append("Entry points other services or clients may call:")
        lines += [""] + [f"- `{_inline(p)}`" for p in apis] + [""]
    consumed = [(c.get("channel"), c.get("broker"))
                for d in _of_kind(docs, "Messaging")
                for c in d.get("spec", {}).get("consumers", [])]
    if consumed:
        lines.append("Events consumed from upstream producers (this service stops receiving "
                     "data when those producers stop publishing):")
        lines += [""] + [f"- `{_inline(ch)}` (broker: `{_inline(br)}`)" for ch, br in consumed] + [""]
    lines += [
        "A single repository cannot see its callers. Run `sre-kb estate` across the fleet to",
        "resolve who actually calls this service, who consumes its events, and which services",
        "share its resources (`DEPENDENCY-MAP.md` in the estate run).",
        "",
    ]
    return "\n".join(lines)


def estate_dependency_map_markdown(topology: dict, docs: list[dict]) -> str:
    """The estate-wide per-service upstream/downstream map (see module docstring)."""
    spec = topology.get("spec", {})
    nodes = {n["name"]: n for n in spec.get("nodes", [])}
    edges = spec.get("edges", [])
    services = sorted(n for n, node in nodes.items() if node.get("type") in ("service", "frontend"))

    publishers_of: dict[str, list[str]] = {}
    consumers_of: dict[str, list[str]] = {}
    for e in edges:
        if e.get("relation") == "publishes":
            publishers_of.setdefault(e["to"], []).append(e["from"])
        if e.get("relation") == "consumes":
            consumers_of.setdefault(e["from"], []).append(e["to"])

    cotenancy = [d for d in docs if d.get("kind") == "BlastRadius"
                 and (d.get("spec", {}).get("coTenancy"))]

    lines = [
        GENERATED,
        "# Estate — upstream/downstream dependency map",
        "",
        "Both directions for every scanned service, resolved across repositories. `upstream`",
        "= who depends on the service; `downstream` = what the service depends on. Generated",
        "from code and manifests — verify against live state.",
        "",
    ]
    for svc in services:
        s = _inline(svc)
        lines += [f"## `{s}`", "", f"### Downstream — what `{s}` depends on", ""]
        down = []
        for e in edges:
            if e.get("from") != svc:
                continue
            rel = e.get("relation")
            if rel in ("binds", "calls", "uses-library", "publishes"):
                target_type = _inline(nodes.get(e["to"], {}).get("type", "-"))
                phrase = _RELATION_PHRASE.get(rel, _inline(rel))
                extra = " — contract: OpenAPI" if e.get("contract") == "openapi" else ""
                down.append(f"- `{_inline(e['to'])}` ({target_type}) — {phrase}{extra}")
        for e in edges:  # topics this service consumes: its input feed is a dependency too
            if e.get("relation") == "consumes" and e.get("to") == svc:
                feeders = ", ".join(f"`{_inline(p)}`" for p in publishers_of.get(e["from"], []))
                fed = f" (published by {feeders})" if feeders else " (no scanned publisher)"
                down.append(f"- `{_inline(e['from'])}` (topic) — consumes events from{fed}")
        lines += down or ["- (none detected)"]
        lines += ["", f"### Upstream — who depends on `{s}`", ""]
        up = []
        for e in edges:
            if e.get("relation") == "calls" and e.get("to") == svc:
                up.append(f"- `{_inline(e['from'])}` calls `{s}` over HTTP — an outage here "
                          f"degrades `{_inline(e['from'])}`")
        for e in edges:
            if e.get("relation") == "publishes" and e.get("from") == svc:
                for c in consumers_of.get(e["to"], []):
                    up.append(f"- `{_inline(c)}` consumes `{_inline(e['to'])}` — it stops "
                              f"receiving data when `{s}` stops publishing")
        for br in cotenancy:
            shared_by = {x for grp in br["spec"].get("coTenancy", [])
                         for x in grp.get("sharedBy", [])}
            if svc in shared_by:
                others = ", ".join(f"`{_inline(o)}`" for o in sorted(shared_by - {svc}))
                res = _inline(br["spec"].get("node", {}).get("name", "-"))
                up.append(f"- shares `{res}` with {others} — a failure there degrades all "
                          f"tenants at once")
                indirect = br["spec"].get("indirectServices", [])
                if indirect:
                    up.append("  - indirect reach via call chains: "
                              + ", ".join(f"`{_inline(i)}`" for i in indirect))
        lines += up or ["- no scanned service depends on it (or its callers are not scanned)"]
        lines.append("")
    return "\n".join(lines)
