"""Property-based tests (hypothesis) for the parser-shaped helpers whose input domain is
untrusted text. The adversarial fixtures cover the failure shapes we know; properties cover
the ones we don't — for these functions a crash IS the bug (a hostile repo must never abort
a scan), so totality and idempotency are the contracts."""

from __future__ import annotations

import re

from hypothesis import given
from hypothesis import strategies as st

from sre_kb.security.secret_scan import redact_text, scan_text
from sre_kb.util import parse_duration_ms, slug

_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@given(st.text(max_size=200))
def test_slug_is_total_valid_and_idempotent(text):
    out = slug(text)
    assert _NAME.match(out), out          # always a valid metadata.name
    assert slug(out) == out               # idempotent: slugging a slug is a no-op


@given(st.text(max_size=50))
def test_parse_duration_is_total(value):
    ms = parse_duration_ms(value)
    assert ms is None or (isinstance(ms, int) and ms >= 0)


@given(st.integers(min_value=0, max_value=10**6), st.sampled_from(["ms", "s", "m"]))
def test_parse_duration_units(n, unit):
    assert parse_duration_ms(f"{n}{unit}") == n * {"ms": 1, "s": 1000, "m": 60_000}[unit]


@given(st.text(max_size=500))
def test_scan_text_is_total_and_grounded(text):
    findings = scan_text(text, "fuzz.txt")
    for f in findings:                    # a finding always points at a real line of the input
        assert f["path"] == "fuzz.txt"
        assert 1 <= f["line"] <= text.count("\n") + 1


@given(st.text(max_size=500))
def test_redaction_quiesces_the_scanner(text):
    """Redact-then-scan must converge: one redaction pass leaves nothing the same pass would
    still redact (the publish override depends on the second gate coming back clean)."""
    once, n1 = redact_text(text)
    twice, n2 = redact_text(once)
    assert twice == once and n2 == 0     # idempotent: nothing left for a second pass
