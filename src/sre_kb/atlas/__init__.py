"""Evidence-backed codebase atlas.

The atlas is intentionally separate from the operational KB artifact registry. It is a
repository-understanding snapshot with its own versioned contract and deterministic projections.
"""

from sre_kb.atlas.runner import AtlasDrift, build_atlas, check_atlas, write_atlas

__all__ = ["AtlasDrift", "build_atlas", "check_atlas", "write_atlas"]
