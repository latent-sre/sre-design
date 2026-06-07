"""Unit tests for the burn-rate expression builder (latency-vs-error SLI + route scoping)."""

from sre_kb.synth.scaffold import burn_rate_expr


def test_latency_burns_on_buckets_scoped_by_route():
    expr, numerator = burn_rate_expr("latency", 800, 0.005, "/api/v1/orders")
    fast = expr["prometheus_fast"]
    # measures latency (histogram buckets), never error rate
    assert 'http_server_requests_seconds_bucket{uri="/api/v1/orders",le="0.8"}' in fast
    assert 'http_server_requests_seconds_count{uri="/api/v1/orders"}' in fast
    assert 'outcome!="SUCCESS"' not in fast
    assert fast.endswith("> 0.072")  # 14.4 * 0.005
    assert expr["prometheus_slow"].endswith("> 0.03")  # 6 * 0.005
    assert "[6h]" in expr["prometheus_slow"]
    assert numerator == "fraction of requests slower than 0.8s"


def test_availability_burns_on_error_ratio_scoped_by_route():
    expr, numerator = burn_rate_expr("availability", None, 0.005, "/api/v1/orders")
    fast = expr["prometheus_fast"]
    assert 'http_server_requests_seconds_count{uri="/api/v1/orders",outcome!="SUCCESS"}' in fast
    assert 'http_server_requests_seconds_count{uri="/api/v1/orders"}' in fast
    assert "bucket" not in fast
    assert numerator == 'error fraction (outcome!="SUCCESS")'


def test_no_route_falls_back_to_unscoped():
    expr, _ = burn_rate_expr("latency", 800, 0.005, None)
    fast = expr["prometheus_fast"]
    assert "uri=" not in fast
    assert 'http_server_requests_seconds_bucket{le="0.8"}' in fast
