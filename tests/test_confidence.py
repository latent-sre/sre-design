"""Signal-derived confidence: ordering, the verified/needs-review partition, and the
per-instance corroboration bonus."""

from __future__ import annotations

from sre_kb.scoring.confidence import Signal, confidence


def test_signal_strength_is_ordered():
    assert confidence(Signal.DIRECT) > confidence(Signal.DERIVED) > confidence(Signal.INFERRED) > confidence(Signal.WEAK)


def test_partition_at_gate_threshold():
    # DIRECT/DERIVED clear the 0.7 verified gate; INFERRED/WEAK never do.
    assert confidence(Signal.DIRECT) >= 0.7 and confidence(Signal.DERIVED) >= 0.7
    assert confidence(Signal.INFERRED) < 0.7 and confidence(Signal.WEAK) < 0.7


def test_corroboration_is_per_instance_capped_and_cannot_cross_the_gate():
    assert confidence(Signal.DERIVED, 4) > confidence(Signal.DERIVED, 1)  # more evidence => higher
    assert confidence(Signal.DIRECT, 50) <= 0.95  # never asserted as certainty
    assert confidence(Signal.INFERRED, 50) < 0.7  # a weak signal stays needs-review regardless
