"""Signal-derived confidence.

Confidence reflects *how direct the extraction was*, not a per-kind constant. A value
near 1.0 is never asserted — these are deterministic extractions, not certainties.

  - DIRECT   an explicit declaration in the source: an annotation, a config literal, a
             manifest binding. The fact is read, not inferred.
  - DERIVED  deterministically composed from DIRECT facts (e.g. a Flow's steps, a
             BlastRadius node). Sound, but one step removed from the source.
  - INFERRED a heuristic/pattern inference with no explicit declaration (a log-pattern
             alert; an SLO guessed from metric buckets). Routed to needs-review.
  - WEAK     speculative; always below the verified threshold.

`confidence()` adds a small corroboration bonus when an artifact is backed by more than
one independent evidence item, so two artifacts of the same class are no longer
indistinguishable. Gating turns the resulting number into verified vs. needs-review.
"""

from __future__ import annotations

from enum import Enum


class Signal(float, Enum):
    DIRECT = 0.9
    DERIVED = 0.8
    INFERRED = 0.6
    WEAK = 0.5


def confidence(signal: Signal, evidence_count: int = 1) -> float:
    """Base signal strength + a capped corroboration bonus for extra evidence items."""
    bonus = min(0.06, 0.03 * max(0, evidence_count - 1))
    return round(min(0.95, float(signal) + bonus), 3)
