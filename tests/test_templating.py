"""The shared Jinja2 rendering environment is the security boundary for free-text projections: it is
sandboxed, fails loud on missing context, and its sanitizing filters are the single definition of how
untrusted repo-derived values are neutralized. These tests pin those guarantees so a future change
can't silently weaken them."""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError
from jinja2.exceptions import SecurityError

from sre_kb.render.templating import env, inline, mermaid, render


def test_inline_flattens_and_defangs():
    # newline-injected bullet collapses to one line; backtick (code-span breakout) dropped.
    assert inline("a\n- evil") == "a - evil"
    assert inline("name`x") == "namex"
    assert inline("  spaced \t out  ") == "spaced out"


def test_mermaid_strips_diagram_metacharacters():
    out = mermaid('svc"; note over X: pwned')
    assert '"' not in out and ";" not in out and ":" not in out
    assert "pwned" in out  # kept as inert text
    assert mermaid("a\nb") == "a b"  # whitespace collapsed before meta-strip


def test_environment_is_sandboxed():
    """A hostile value reaching a template expression cannot escalate to attribute-level attacks."""
    with pytest.raises(SecurityError):
        env().from_string("{{ x.__class__.__mro__ }}").render(x=1)


def test_strict_undefined_fails_loud():
    """A missing context key is a render-time error, not a silent blank that ships a broken artifact."""
    with pytest.raises(UndefinedError):
        env().from_string("{{ missing }}").render()


def test_filters_are_registered_in_the_environment():
    assert env().filters["inline"] is inline
    assert env().filters["mermaid"] is mermaid
    # filters are usable from within a template, not just as Python functions
    assert env().from_string("{{ v | inline }}").render(v="x`y") == "xy"


def test_render_loads_a_packaged_template():
    """`render` resolves real template files from the package templates dir."""
    out = render("copilot-instructions.md.j2", generated="<!-- g -->", service="svc",
                 rules=[], advisories=[], flows=[])
    assert out.startswith("<!-- g -->")
    assert "## Reliability guardrails" in out
    assert "- (none detected)" in out
