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
    rendered_targets,
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


# --- new backends: honest coverage (HYBRID-PLAN §9.3 #4) ------------------------------------------
def test_wavefront_availability_is_a_wql_burn_rate_ratio():
    expr = render_burn_rate(
        BurnRateIntent("availability", None, 0.005, "/x"), tools=("wavefront",)
    )
    fast = expr["wavefront_fast"]
    assert fast.startswith("msum(1h, rate(ts(")
    assert 'not outcome="SUCCESS"' in fast and 'uri="/x"' in fast
    assert fast.endswith("> 0.072")  # 14.4 * 0.005, same budget math as Prometheus


def test_wavefront_latency_is_a_labelled_percentile_not_a_fake_burn_rate():
    expr = render_burn_rate(
        BurnRateIntent("latency", 800, 0.005, "/x", "p99"), tools=("wavefront",)
    )
    wf = expr["wavefront"]
    assert wf["query"] == 'ts("http.server.requests", uri="/x" and phi="0.99") > 0.8'
    # the mechanism is honestly labelled as NOT a budget burn-rate (it's a different mechanism)
    assert "NOT a multi-window budget burn-rate" in wf["mechanism"]
    assert "wavefront_fast" not in expr  # no fabricated le-bucket ratio for Wavefront


def test_appdynamics_is_a_structured_health_rule_not_a_query():
    expr = render_burn_rate(
        BurnRateIntent("latency", 800, 0.005, "/api/v1/orders", "p95"), tools=("appdynamics",)
    )
    hr = expr["appdynamics"]["healthRule"]
    assert hr["metricPath"].endswith("95th Percentile Response Time (ms)")
    assert "<tier>" in hr["metricPath"] and "<business-transaction>" in hr["metricPath"]
    assert hr["condition"] == "> 800 ms"
    assert "not a query" in expr["appdynamics"]["mechanism"]


def test_percentile_accepts_p_prefixed_or_bare():
    bare = render_burn_rate(BurnRateIntent("latency", 800, 0.005, "/x", 99), tools=("wavefront",))
    pfx = render_burn_rate(BurnRateIntent("latency", 800, 0.005, "/x", "p99"), tools=("wavefront",))
    assert bare["wavefront"]["query"] == pfx["wavefront"]["query"]


def test_rendered_targets_reports_only_real_backends():
    # burn-rate latency: Prometheus + Wavefront + AppDynamics render; Splunk has no burn-rate.
    expr = render_burn_rate(BurnRateIntent("latency", 800, 0.005, "/x", "p99"))  # default tools
    assert rendered_targets(render_burn_rate(BurnRateIntent("latency", 800, 0.005, "/x", "p99"),
                                             tools=("prometheus", "splunk", "wavefront", "appdynamics"))) == [
        "prometheus", "wavefront", "appdynamics"]
    # log-pattern: Prometheus key is present but null (no metric), so it is NOT a render target.
    lp = render_log_pattern(LogPatternIntent("boom", "svc"))
    assert rendered_targets(lp) == ["splunk"]
    assert "prometheus_fast" in expr  # sanity: default tools still produce Prometheus
