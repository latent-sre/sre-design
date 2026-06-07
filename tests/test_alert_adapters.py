"""The tool-neutral alert adapter seam (HYBRID-PLAN Phase 5 / §9.3 #4).

These pin the seam itself: backend selection, the per-tool fragments, and that an adapter returns
nothing for an intent it can't express. The exact Prometheus/Splunk strings are pinned by
test_burn_rate_expr.py and test_e2e_scan.py — here we test the wiring.
"""

from __future__ import annotations

from sre_kb.render.alerts import (
    BurnRateIntent,
    LogPatternIntent,
    render_burn_rate,
    render_log_pattern,
)


def test_burn_rate_default_tools_emit_prometheus_and_windows():
    expr = render_burn_rate(BurnRateIntent("latency", 800, 0.005, "/api/v1/orders"))
    assert set(expr) == {"prometheus_fast", "prometheus_slow", "windows"}
    assert 'le="0.8"' in expr["prometheus_fast"]


def test_tool_selection_narrows_backends():
    # Selecting only splunk yields no Prometheus burn-rate (Splunk has no derived metric for it).
    expr = render_burn_rate(BurnRateIntent("latency", 800, 0.005, "/x"), tools=("splunk",))
    assert expr == {"windows": expr["windows"]}  # only the neutral windows label remains
    assert "prometheus_fast" not in expr


def test_log_pattern_default_emits_splunk_and_null_prometheus():
    expr = render_log_pattern(LogPatternIntent(search="order.created failed", service="orders"))
    assert expr["prometheus"] is None  # no metric for a pure log pattern
    assert expr["splunk"] == 'index=app sourcetype=orders "order.created failed" | stats count by host'


def test_log_pattern_tool_selection():
    expr = render_log_pattern(LogPatternIntent("boom", "svc"), tools=("prometheus",))
    assert expr == {"prometheus": None}  # Prometheus selected only -> no splunk key


def test_unknown_tool_is_ignored():
    expr = render_burn_rate(BurnRateIntent("availability", None, 0.01, None), tools=("nope",))
    assert expr == {"windows": expr["windows"]}
