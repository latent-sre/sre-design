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
