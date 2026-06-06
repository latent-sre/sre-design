"""Mermaid rendering sanitizes untrusted labels so a hostile manifest/annotation name can't
break out of a label or inject diagram syntax (render-integrity)."""

from __future__ import annotations

from sre_kb.render.diagrams import mermaid_sequence, mermaid_topology


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
