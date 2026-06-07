"""Unit tests for the burn-rate expression builder (latency-vs-error SLI + route scoping)."""

from sre_kb.synth.scaffold import burn_rate_expr


def test_latency_burns_on_buckets_scoped_by_route():
    expr, numerator = burn_rate_expr("latency", 800, 0.005, "/api/v1/orders")
    fast = expr["prometheus_fast"]
    # measures latency (histogram buckets), never error rate
    assert 'http_server_requests_seconds_bucket{uri="/api/v1/orders",le="0.8"}' in fast
    assert 'http_server_requests_seconds_count{uri="/api/v1/orders"}' in fast
    assert 'outcome!="SUCCESS"' not in fast
    # multi-window/multi-burn-rate: the 1h long window AND a 5m short confirmation window
    assert " and " in fast and "[1h]" in fast and "[5m]" in fast
    assert "> 0.072)" in fast  # 14.4 * 0.005, applied to both windows
    slow = expr["prometheus_slow"]
    assert "[6h]" in slow and "[30m]" in slow and "> 0.03)" in slow  # 6 * 0.005
    assert numerator == "fraction of requests slower than 0.8s"


def test_availability_burns_on_error_ratio_scoped_by_route():
    expr, numerator = burn_rate_expr("availability", None, 0.005, "/api/v1/orders")
    fast = expr["prometheus_fast"]
    assert 'http_server_requests_seconds_count{uri="/api/v1/orders",outcome!="SUCCESS"}' in fast
    assert 'http_server_requests_seconds_count{uri="/api/v1/orders"}' in fast
    assert "bucket" not in fast
    # multi-window/multi-burn-rate: the 1h long window AND a 5m short confirmation window
    assert " and " in fast and "[1h]" in fast and "[5m]" in fast
    assert numerator == 'error fraction (outcome!="SUCCESS")'


def test_no_route_falls_back_to_unscoped():
    expr, _ = burn_rate_expr("latency", 800, 0.005, None)
    fast = expr["prometheus_fast"]
    assert "uri=" not in fast
    assert 'http_server_requests_seconds_bucket{le="0.8"}' in fast
