"""Dashboard panel generation (HYBRID-PLAN Phase 5 / §9.6 — the adopted `Dashboard` kind).

Mirrors the alert-adapter seam (`render/alerts.py`): a tool-neutral set of panels rendered into a
backend's query dialect. Today the engine generates the standard RED panels (rate / errors /
duration) for a flow's route, Prometheus-sourced — the one backend we can derive dashboard queries
for deterministically. Other sources (Grafana/Wavefront dashboards) plug in the same way as the
alert backends did, and are the next Phase-5 increment.
"""

from __future__ import annotations

_BURN_METRIC = "http_server_requests_seconds"  # Micrometer/Prometheus HTTP server timer base name


def _sel(*selectors: str) -> str:
    parts = [s for s in selectors if s]
    return "{" + ",".join(parts) + "}" if parts else ""


def _pctl(percentile, default: float) -> float:
    if percentile is None:
        return default
    try:
        return float(str(percentile).lstrip("pP")) / 100
    except ValueError:
        return default


def red_panels(route: str | None, *, percentile=None, source: str = "prometheus") -> list[dict]:
    """The RED method (Rate, Errors, Duration) as dashboard panels for `route`.

    Returns tool-neutral panel dicts whose `signal` carries the backend `source` + a generated
    `query`. Prometheus only today; an unknown source yields panels with the metric but no query
    (honest: we don't fabricate a dialect we can't generate).
    """
    uri = f'uri="{route}"' if route else ""
    phi = _pctl(percentile, 0.99)
    if source == "prometheus":
        tot_sel = _sel(uri)
        err_sel = _sel(uri, 'outcome!="SUCCESS"')
        dur_q = f"histogram_quantile({phi:g}, sum(rate({_BURN_METRIC}_bucket{tot_sel}[5m])) by (le))"
        rate_q = f"sum(rate({_BURN_METRIC}_count{tot_sel}[5m]))"
        err_q = (
            f"sum(rate({_BURN_METRIC}_count{err_sel}[5m])) "
            f"/ sum(rate({_BURN_METRIC}_count{tot_sel}[5m]))"
        )
    else:
        dur_q = rate_q = err_q = None

    def _panel(title: str, ptype: str, unit: str, metric: str, query: str | None, desc: str) -> dict:
        signal = {"source": source, "metric": metric, "description": desc}
        if query is not None:
            signal["query"] = query
        return {"title": title, "type": ptype, "unit": unit, "signal": signal}

    return [
        _panel("Request rate", "timeseries", "req/s", f"{_BURN_METRIC}_count", rate_q,
               "throughput (RED: Rate)"),
        _panel("Error fraction", "timeseries", "percentunit", f"{_BURN_METRIC}_count", err_q,
               "fraction of non-SUCCESS responses (RED: Errors)"),
        _panel(f"Latency p{int(phi * 100)}", "timeseries", "s", f"{_BURN_METRIC}_bucket", dur_q,
               "request-duration percentile from the histogram (RED: Duration)"),
    ]
