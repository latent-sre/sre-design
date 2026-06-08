"""FactSet query helpers: the type index is order-preserving and invalidates on add()."""

from __future__ import annotations

from sre_kb.models.envelope import Evidence, Lines
from sre_kb.models.facts import Fact, FactSet

_EV = Evidence(
    repo="file://x", commit="0" * 40, path="p", lines=Lines(start=1, end=1),
    excerptHash="sha256:" + "0" * 64, detector="t",
)


def _f(t: str) -> Fact:
    return Fact(t, {}, _EV)


def test_of_is_order_preserving_and_invalidates_on_add():
    fs = FactSet()
    fs.add(_f("a"), _f("b"), _f("a"))
    assert len(fs.of("a")) == 2
    assert fs.first("a") is fs.of("a")[0]                 # first == first-inserted of that type
    assert [x.type for x in fs.of("a", "b")] == ["a", "b", "a"]  # multi-type keeps global order

    fs.add(_f("a"))                                       # index invalidated, rebuilt lazily
    assert len(fs.of("a")) == 3
    assert fs.of("c") == []                               # unknown type -> empty
