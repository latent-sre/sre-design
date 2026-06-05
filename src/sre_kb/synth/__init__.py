"""Deterministic scaffolding: turn a FactSet into schema-tagged KB artifacts.

The engine fills every field it can prove (with provenance) and marks the rest for
Copilot enrichment. This module never calls an LLM.
"""

from sre_kb.synth.scaffold import scaffold

__all__ = ["scaffold"]
