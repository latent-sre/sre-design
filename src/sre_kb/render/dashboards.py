"""Dashboard panel generation (HYBRID-PLAN Phase 5 / §9.6 — the adopted `Dashboard` kind).

Mirrors the alert-adapter seam (`render/alerts.py`): a tool-neutral set of panels rendered into a
backend's query dialect. The engine generates the standard RED panels (rate / errors / duration)
for a flow's route, with deterministic queries for Prometheus, Grafana (over a Prometheus
datasource), and Wavefront (WQL); splunk/appdynamics panels carry the metric but no query, since
those backends have no faithful RED dashboard dialect.
"""

from __future__ import annotations

from sre_kb.render.alerts import _label_match, _pctl

_BURN_METRIC = "http_server_requests_seconds"  # Micrometer/Prometheus HTTP server timer base name


def _sel(*selectors: str) -> str:
    parts = [s for s in selectors if s]
    return "{" + ",".join(parts) + "}" if parts else ""


def red_panels(route: str | None, *, percentile=None, source: str = "prometheus") -> list[dict]:
    """The RED method (Rate, Errors, Duration) as dashboard panels for `route`.

    Returns tool-neutral panel dicts whose `signal` carries the backend `source` + a generated
    `query` for Prometheus, Grafana (Prometheus datasource), and Wavefront (WQL); a source without a
    faithful RED dialect yields panels with the metric but no query (honest: no fabricated dialect).
    """
    uri = _label_match("uri", route) if route else ""  # escaped, like the alert adapters
    pct = _pctl(percentile, 99)  # one shared percentile normalizer (e.g. 99.9 stays 99.9)
    phi = pct / 100  # dashboards want a fraction
    rate_q = err_q = dur_q = None
    if source in ("prometheus", "grafana"):
        # Grafana dashboards query a Prometheus datasource, so reuse the deterministic PromQL.
        tot_sel = _sel(uri)
        err_sel = _sel(uri, 'outcome!="SUCCESS"')
        dur_q = f"histogram_quantile({phi:g}, sum(rate({_BURN_METRIC}_bucket{tot_sel}[5m])) by (le))"
        rate_q = f"sum(rate({_BURN_METRIC}_count{tot_sel}[5m]))"
        err_q = (
            f"sum(rate({_BURN_METRIC}_count{err_sel}[5m])) "
            f"/ sum(rate({_BURN_METRIC}_count{tot_sel}[5m]))"
        )
    elif source == "wavefront":
        def _ts(metric: str, extra: str = "") -> str:
            clauses = " and ".join(c for c in (uri, extra) if c)
            return f'ts("{metric}", {clauses})' if clauses else f'ts("{metric}")'

        tot = _ts("http.server.requests.count")
        errs = _ts("http.server.requests.count", 'not outcome="SUCCESS"')
        rate_q = f"rate({tot})"
        err_q = f"rate({errs}) / rate({tot})"
        dur_q = _ts("http.server.requests", f'phi="{phi:g}"')
    # splunk/appdynamics have no faithful RED dashboard query dialect -> panels carry no query

    dur_desc = (
        "request-duration percentile from the histogram (RED: Duration)"
        if source in ("prometheus", "grafana")
        else "request-duration percentile series (RED: Duration)"
    )

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
        _panel(f"Latency p{pct:g}", "timeseries", "s", f"{_BURN_METRIC}_bucket", dur_q,
               dur_desc),
    ]
