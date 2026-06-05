"""Layered validation: structural (here) -> provenance -> crossref -> gating.

Only the structural layer is implemented in Phase 0; the rest land with the P1 slice.
Nothing is ever silently dropped — failures downgrade status and are reported.
"""

from sre_kb.validation.structural import (
    StructuralError,
    validate_doc,
    validate_kb_tree,
)

__all__ = ["StructuralError", "validate_doc", "validate_kb_tree"]
