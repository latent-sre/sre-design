"""Render validated KB artifacts into projections: Mermaid diagrams, Copilot
instructions (with reliability guardrails), runbook markdown, and the Backstage catalog.

Projections are GENERATED from the KB (the source of truth) and never hand-edited.
"""

from sre_kb.render.project import load_kb, render_projections

__all__ = ["load_kb", "render_projections"]
