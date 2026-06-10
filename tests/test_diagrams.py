"""Mermaid rendering sanitizes untrusted labels so a hostile manifest/annotation name can't
break out of a label or inject diagram syntax (render-integrity)."""

from __future__ import annotations

from sre_kb.render.diagrams import (
    TOPOLOGY_LEGEND,
    diagram_markdown,
    mermaid_sequence,
    mermaid_topology,
)


def test_sequence_sanitizes_untrusted_service_and_step_names():
    flow = {
        "metadata": {"service": 'svc"; note over X: pwned'},
        "spec": {
            "trigger": {"method": "GET", "path": "/orders"},
            "steps": [{"kind": "db-write", "name": "persist; note over Y: x"}],
        },
    }
    out = mermaid_sequence(flow)
    assert '"' not in out and ";" not in out  # no breakout characters survive
    assert "pwned" in out and "persist" in out  # kept as inert text, just defanged
    assert "/orders" in out  # benign characters are preserved


def test_topology_sanitizes_node_labels_and_edge_relations():
    topo = {"spec": {
        "nodes": [{"type": "datastore", "name": 'db"]; evil'}],
        "edges": [{"from": 'db"]; evil', "to": "svc", "relation": "binds|x"}],
    }}
    out = mermaid_topology(topo)
    assert '"]' not in out   # cannot close the [("...")] shape early
    assert "|x" not in out   # edge-label pipe injection neutralized


def test_topology_styles_only_engine_known_types():
    """Node styling comes from the fixed engine vocabulary: known types get a class +
    classDef; an unknown (possibly hand-authored) type never reaches a style line, so
    scanned strings cannot inject Mermaid class syntax."""
    topo = {"spec": {
        "nodes": [{"type": "service", "name": "svc"},
                  {"type": "topic", "name": "order.created"},
                  {"type": "weird;classDef pwn fill:#000", "name": "x"}],
        "edges": [],
    }}
    out = mermaid_topology(topo)
    assert "class n_svc service" in out
    assert "classDef service" in out and "classDef topic" in out
    assert "pwn" not in out


def test_diagram_markdown_wraps_fenced_mermaid_with_legend():
    md = diagram_markdown("estate topology", "graph LR", TOPOLOGY_LEGEND)
    assert "```mermaid\ngraph LR\n```" in md  # GitHub renders this inline
    assert "Legend:" in md


def test_topology_tolerates_malformed_nodes_and_edges():
    """A partially-extracted Topology (a node with no name, an edge missing an endpoint) must render
    the well-formed parts rather than KeyError."""
    topo = {"spec": {
        "nodes": [{"type": "service", "name": "svc"}, {"type": "datastore"}],  # 2nd has no name
        "edges": [{"from": "svc", "to": "db", "relation": "reads"}, {"from": "svc"}],  # 2nd has no to
    }}
    out = mermaid_topology(topo)               # does not raise
    assert "n_svc" in out and "reads" in out   # the well-formed node/edge rendered
    assert out.count("-->") == 1               # the malformed edge was skipped


def test_topology_tier_coloring_uses_only_the_fixed_vocabulary():
    """A service node with a known criticality tier gets the tier class instead of the plain
    service class; a tier value outside the engine vocabulary never reaches a style line."""
    from sre_kb.render.diagrams import topology_overlays

    topo = {"spec": {"nodes": [{"type": "service", "name": "orders"},
                               {"type": "service", "name": "billing"}], "edges": []}}
    docs = [
        {"kind": "Criticality", "metadata": {"service": "orders"}, "spec": {"tier": "tier0"}},
        {"kind": "Criticality", "metadata": {"service": "billing"},
         "spec": {"tier": "evil;classDef pwn fill:#000"}},
    ]
    tiers, lossy = topology_overlays(topo, docs)
    out = mermaid_topology(topo, tiers=tiers, lossy=lossy)
    assert "class n_orders tier0" in out and "classDef tier0" in out
    assert "class n_billing service" in out   # unknown tier -> plain service style
    assert "pwn" not in out


def test_topology_lossy_node_styles_incoming_edges():
    """Edges feeding a data-loss node render red-dashed via linkStyle; indices skip
    malformed edges so the style lands on the drawn edge, not a phantom index."""
    from sre_kb.render.diagrams import topology_overlays

    topo = {"spec": {
        "nodes": [{"type": "service", "name": "orders"},
                  {"type": "datastore", "name": "orders-postgres"}],
        "edges": [{"from": "orders"},  # malformed: skipped, consumes no linkStyle index
                  {"from": "orders", "to": "orders-postgres", "relation": "binds"}],
    }}
    docs = [{"kind": "BlastRadius", "metadata": {"name": "orders-postgres-x"},
             "spec": {"node": {"type": "datastore", "name": "orders-postgres"},
                      "stateful": {"dataLossRisk": True}}}]
    tiers, lossy = topology_overlays(topo, docs)
    assert lossy == {"orders-postgres"}
    out = mermaid_topology(topo, tiers=tiers, lossy=lossy)
    assert "linkStyle 0 stroke:#d93025" in out


def test_lossy_attribution_falls_back_to_the_sole_node_of_type():
    """A single-service BlastRadius names the code-side target (repository slug); when the
    topology has exactly one datastore node, the write can only be going there."""
    from sre_kb.render.diagrams import topology_overlays

    topo = {"spec": {
        "nodes": [{"type": "service", "name": "orders"},
                  {"type": "datastore", "name": "orders-postgres"}],
        "edges": [{"from": "orders", "to": "orders-postgres", "relation": "binds"}],
    }}
    docs = [{"kind": "BlastRadius", "metadata": {"name": "order-repository"},
             "spec": {"node": {"type": "datastore", "name": "order-repository"},
                      "stateful": {"dataLossRisk": True}}}]
    _, lossy = topology_overlays(topo, docs)
    assert lossy == {"orders-postgres"}


def test_lossy_attribution_never_guesses_between_two_nodes_of_type():
    from sre_kb.render.diagrams import topology_overlays

    topo = {"spec": {
        "nodes": [{"type": "datastore", "name": "db-a"}, {"type": "datastore", "name": "db-b"}],
        "edges": [],
    }}
    docs = [{"kind": "BlastRadius", "metadata": {"name": "x"},
             "spec": {"node": {"type": "datastore", "name": "some-repo"},
                      "stateful": {"dataLossRisk": True}}}]
    _, lossy = topology_overlays(topo, docs)
    assert lossy == set()  # ambiguous -> no styling, never a guessed edge


def test_sequence_names_known_http_clients_as_participants():
    """An http-egress step whose sink target is a configured client renders as a named
    participant; without the join (or for unknown targets) it stays the Downstream catch-all."""
    flow = {
        "metadata": {"service": "orders"},
        "spec": {
            "trigger": {"method": "POST", "path": "/orders"},
            "steps": [{"id": "s0", "kind": "http-egress", "name": "call-inventory"},
                      {"id": "s1", "kind": "db-write", "name": "persist"}],
            "sinks": [{"type": "http", "target": "inventory"},
                      {"type": "db", "target": "order-repository"}],
        },
    }
    out = mermaid_sequence(flow, known_targets={"inventory": "inventory"})
    assert "participant P_inventory as inventory" in out
    assert "SVC->>P_inventory: call-inventory" in out
    assert "Downstream" not in out
    assert "SVC->>Datastore: persist" in out          # non-http steps keep the vocabulary
    assert "Downstream" in mermaid_sequence(flow)     # no join -> unchanged output


def test_sequence_with_mismatched_sinks_never_mispairs():
    """Steps and sinks are index-parallel only by construction; a hand-authored flow with
    unequal lengths keeps every generic participant instead of guessing the pairing."""
    flow = {
        "metadata": {"service": "orders"},
        "spec": {
            "trigger": {"method": "GET", "path": "/x"},
            "steps": [{"id": "s0", "kind": "http-egress", "name": "call-a"},
                      {"id": "s1", "kind": "http-egress", "name": "call-b"}],
            "sinks": [{"type": "http", "target": "inventory"}],
        },
    }
    out = mermaid_sequence(flow, known_targets={"inventory": "inventory"})
    assert "P_inventory" not in out and out.count("Downstream") == 2


def test_multi_service_topology_groups_into_subgraphs():
    """Estate topologies cluster each service with its exclusive resources; anything touched
    by 2+ services lands in the shared (co-tenant) cluster — the drawing that makes blast
    radius legible. Single-service topologies stay flat."""
    topo = {"spec": {
        "nodes": [{"type": "service", "name": "orders"},
                  {"type": "service", "name": "billing"},
                  {"type": "datastore", "name": "shared-db"},
                  {"type": "datastore", "name": "orders-db"},
                  {"type": "topic", "name": "order.created"}],
        "edges": [{"from": "orders", "to": "shared-db", "relation": "binds"},
                  {"from": "billing", "to": "shared-db", "relation": "binds"},
                  {"from": "orders", "to": "orders-db", "relation": "binds"},
                  {"from": "orders", "to": "order.created", "relation": "publishes"},
                  {"from": "order.created", "to": "billing", "relation": "consumes"}],
    }}
    out = mermaid_topology(topo)
    assert 'subgraph sg_orders["orders"]' in out
    assert 'subgraph sg_billing["billing"]' in out
    # The label passes through the Mermaid sanitizer, which strips the parens.
    shared = out.split('subgraph sg_shared__co_tenant_["shared co-tenant"]')[1].split("end")[0]
    assert "n_shared_db" in shared and "n_order_created" in shared
    orders_cluster = out.split('subgraph sg_orders')[1].split("end")[0]
    assert "n_orders_db" in orders_cluster

    flat = mermaid_topology({"spec": {
        "nodes": [{"type": "service", "name": "orders"},
                  {"type": "datastore", "name": "orders-db"}],
        "edges": [{"from": "orders", "to": "orders-db", "relation": "binds"}],
    }})
    assert "subgraph" not in flat


def test_subgraph_titles_are_sanitized():
    """Cluster titles come from scanned service names — breakout characters are defanged."""
    topo = {"spec": {
        "nodes": [{"type": "service", "name": 'svc"]; evil'},
                  {"type": "service", "name": "other"}],
        "edges": [],
    }}
    out = mermaid_topology(topo)
    assert "subgraph" in out and '"]' not in out.replace('"]\n', "")  # label can't close early
    assert "evil" in out  # kept as inert text
