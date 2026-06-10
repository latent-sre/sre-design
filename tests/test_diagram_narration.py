"""Tier-B diagram narration (§3.2/§2.6): captions apply only to diagrams the run actually
rendered, sanitized to one plain paragraph, always labeled advisory."""

from __future__ import annotations

import json
from pathlib import Path

from sre_kb.pipeline.diagram_narration import PROPOSALS_REL, apply_narrations, diagram_docs
from sre_kb.workspace import RunLayout

_DOCS = [
    {"kind": "Flow", "metadata": {"name": "create-order"}, "spec": {}},
    {"kind": "Topology", "metadata": {"name": "order-service"}, "spec": {}},
    {"kind": "Alert", "metadata": {"name": "not-a-diagram"}, "spec": {}},
]


def _layout(tmp_path) -> RunLayout:
    layout = RunLayout(tmp_path / "work", "narr")
    diagrams = layout.root / "projections" / "diagrams"
    diagrams.mkdir(parents=True)
    (diagrams / "create-order.md").write_text("# create-order — flow\n\n```mermaid\nx\n```\n",
                                              encoding="utf-8")
    (diagrams / "order-service-topology.md").write_text("# topo\n", encoding="utf-8")
    return layout


def _proposals(tmp_path, narrations) -> Path:
    target = tmp_path / "target"
    (target / ".sre").mkdir(parents=True)
    p = target / PROPOSALS_REL
    p.write_text(json.dumps({"narrations": narrations}), encoding="utf-8")
    return p


def test_diagram_docs_selects_only_diagram_bearing_kinds():
    assert [d["metadata"]["name"] for d in diagram_docs(_DOCS)] == ["create-order", "order-service"]


def test_narrations_apply_only_to_rendered_diagrams_and_are_labeled_advisory(tmp_path):
    layout = _layout(tmp_path)
    p = _proposals(tmp_path, [
        {"diagram": "create-order", "text": "Shows the order flow.\nWorry about ```the db```."},
        {"diagram": "order-service", "text": "The service graph."},
        {"diagram": "ghost", "text": "no such drawing"},
        {"diagram": "not-a-diagram", "text": "an Alert is not a drawing"},
    ])
    result = apply_narrations(layout, _DOCS, p)
    by = {o.diagram: o.result for o in result.outcomes}
    assert by == {"create-order": "applied", "order-service": "applied",
                  "ghost": "unknown-diagram", "not-a-diagram": "unknown-diagram"}
    md = (layout.root / "projections" / "diagrams" / "create-order.md").read_text()
    assert "**Narration (LLM, advisory)**" in md
    # Sanitized: one plain paragraph — no backticks (fence injection), no raw newlines.
    caption = md.split("advisory)** — verify against the drawing: ", 1)[1]
    assert "`" not in caption and "\n" not in caption.rstrip("\n")
    assert "Worry about the db" in caption


def test_missing_proposals_file_is_a_noop(tmp_path):
    layout = _layout(tmp_path)
    result = apply_narrations(layout, _DOCS, tmp_path / "absent.json")
    assert result.outcomes == []
