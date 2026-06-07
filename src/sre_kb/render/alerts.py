"""Tool-neutral alert intent + per-backend expression adapters (HYBRID-PLAN Phase 5 / §9.3 #4).

An `Alert` artifact's `spec.expr` is the only monitoring-tool-specific payload the engine emits.
Rather than hard-code one backend, the scaffolder builds a tool-neutral **intent** (what to
measure) and each registered **adapter** renders that intent into its own query dialect. Adding a
backend is a new adapter here — not a change to extraction, scaffolding, or gating.

Two intents cover what the engine produces today:
  - `BurnRateIntent`   — a multi-window error-budget burn-rate on an SLO's own SLI.
  - `LogPatternIntent` — a log-search alert for a swallowed-failure message (no metric exists yet).

An adapter is a `(intent) -> dict` fragment; `render_*` merges the fragments of the selected tools
into the `expr` dict. An adapter returns `{}` for an intent it can't express (e.g. Prometheus has
no query for a pure log pattern; Splunk has no derived metric for a burn-rate).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_BURN_METRIC = "http_server_requests_seconds"  # Micrometer/Prometheus HTTP server timer base name

# Standard multi-window burn-rate pair: (expr-key suffix, window, budget multiplier).
BURN_WINDOWS = (("fast", "1h", 14.4), ("slow", "6h", 6.0))
_WINDOWS_LABEL = "multi-window (1h fast @14.4x, 6h slow @6x)"

# Backends rendered when config doesn't narrow them (config: `render.alert_tools`).
DEFAULT_ALERT_TOOLS: tuple[str, ...] = ("prometheus", "splunk")


def _le(threshold_ms: float | int) -> str:
    """A latency threshold in ms -> a Prometheus histogram `le` label in seconds (800 -> '0.8')."""
    return ("%f" % (float(threshold_ms) / 1000)).rstrip("0").rstrip(".")


def _pctl(percentile: int | float | str | None, default: int) -> int | float:
    """Normalize a percentile from 'p99' / '99' / 99 / 99.9 to a number (default when absent)."""
    if percentile is None:
        return default
    try:
        n = float(str(percentile).lstrip("pP"))
    except ValueError:
        return default
    return int(n) if n.is_integer() else n


def _sel(*selectors: str) -> str:
    """Join non-empty Prometheus label selectors into a `{...}` block ('' if none)."""
    parts = [s for s in selectors if s]
    return "{" + ",".join(parts) + "}" if parts else ""


@dataclass(frozen=True)
class BurnRateIntent:
    """A burn-rate alert's tool-neutral meaning. `sli == 'latency'` (with a threshold) measures the
    fraction of requests slower than the threshold; anything else measures the error fraction.
    `percentile` is the SLO's latency percentile (e.g. 99), used by backends that express latency as
    a percentile threshold rather than a histogram-bucket ratio."""

    sli: str
    threshold_ms: float | int | None
    budget_frac: float
    route: str | None
    percentile: int | float | None = None

    @property
    def is_latency(self) -> bool:
        return self.sli == "latency" and self.threshold_ms is not None

    @property
    def numerator(self) -> str:
        """Human phrase for the numerator, reused in the alert rationale (tool-neutral)."""
        if self.is_latency:
            return f"fraction of requests slower than {_le(self.threshold_ms)}s"
        return 'error fraction (outcome!="SUCCESS")'


@dataclass(frozen=True)
class LogPatternIntent:
    """A log-search alert for a swallowed-failure message no metric yet covers."""

    search: str
    service: str
    group_by: str = "host"


# --- Prometheus adapter ---------------------------------------------------------------------------
def _prometheus_burn(intent: BurnRateIntent) -> dict:
    uri_sel = f'uri="{intent.route}"' if intent.route else ""
    out = {}
    for key, window, mult in BURN_WINDOWS:
        thr = round(mult * intent.budget_frac, 6)
        if intent.is_latency:
            tot = _sel(uri_sel)
            within = _sel(uri_sel, f'le="{_le(intent.threshold_ms)}"')
            total = f"sum(rate({_BURN_METRIC}_count{tot}[{window}]))"
            within_term = f"sum(rate({_BURN_METRIC}_bucket{within}[{window}]))"
            out[f"prometheus_{key}"] = f"({total} - {within_term}) / {total} > {thr}"
        else:
            errs = _sel(uri_sel, 'outcome!="SUCCESS"')
            tot = _sel(uri_sel)
            errors = f"sum(rate({_BURN_METRIC}_count{errs}[{window}]))"
            total = f"sum(rate({_BURN_METRIC}_count{tot}[{window}]))"
            out[f"prometheus_{key}"] = f"{errors} / {total} > {thr}"
    return out


def _prometheus_log(_: LogPatternIntent) -> dict:
    return {"prometheus": None}  # a pure log pattern has no metric to query


# --- Splunk adapter -------------------------------------------------------------------------------
def _splunk_burn(_: BurnRateIntent) -> dict:
    return {}  # no derived metric search for a burn-rate; Prometheus owns the metric path


def _splunk_log(intent: LogPatternIntent) -> dict:
    return {
        "splunk": f'index=app sourcetype={intent.service} "{intent.search}" '
        f"| stats count by {intent.group_by}"
    }


# --- Wavefront adapter (WQL) ----------------------------------------------------------------------
def _wf_ts(metric: str, *clauses: str) -> str:
    flt = " and ".join(c for c in clauses if c)
    return f'ts("{metric}", {flt})' if flt else f'ts("{metric}")'


def _wavefront_burn(intent: BurnRateIntent) -> dict:
    """Wavefront WQL. Availability burns as a moving-window error-fraction ratio (faithful to the
    intent). Latency has no le-bucket series in Micrometer's Wavefront registry, so it is rendered
    as a percentile threshold — a *different* mechanism, labelled as such, not a budget burn-rate."""
    route = f'uri="{intent.route}"' if intent.route else ""
    if intent.is_latency:
        pct = _pctl(intent.percentile, 99)
        phi = f"{pct / 100:g}"  # 99 -> "0.99"
        series = _wf_ts("http.server.requests", route, f'phi="{phi}"')
        return {
            "wavefront": {
                "query": f"{series} > {_le(intent.threshold_ms)}",
                "mechanism": (
                    f"static p{pct} latency threshold in seconds (requires Micrometer "
                    f"publishPercentiles); Wavefront has no le-bucket series, so this is a "
                    f"p{pct} <= {intent.threshold_ms}ms check, NOT a multi-window budget burn-rate"
                ),
            }
        }
    out: dict = {}
    not_success = 'not outcome="SUCCESS"'
    for key, window, mult in BURN_WINDOWS:
        thr = round(mult * intent.budget_frac, 6)
        err_series = _wf_ts("http.server.requests.count", route, not_success)
        tot_series = _wf_ts("http.server.requests.count", route)
        num = f"msum({window}, rate({err_series}))"
        den = f"msum({window}, rate({tot_series}))"
        out[f"wavefront_{key}"] = f"{num} / {den} > {thr}"
    return out


# --- AppDynamics adapter (Health Rule, not a query) -----------------------------------------------
def _appdynamics_burn(intent: BurnRateIntent) -> dict:
    """AppDynamics alerts via Health Rules (a metric path + a condition), not a query language, and
    it has no error-budget burn-rate. So this emits a structured, clearly-templated Health Rule the
    reviewer maps to their tier/BT — never a fabricated query string."""
    scope = intent.route or "this flow"
    if intent.is_latency:
        pct = _pctl(intent.percentile, 95)
        metric = f"{pct}th Percentile Response Time (ms)"
        condition = f"> {intent.threshold_ms} ms"
    else:
        metric = "Error Rate"
        condition = f"> {round(intent.budget_frac * 100, 3)}% (SLO error budget as a static threshold)"
    return {
        "appdynamics": {
            "healthRule": {
                "metricPath": (
                    f"Business Transaction Performance|Business Transactions|"
                    f"<tier>|<business-transaction>|{metric}"
                ),
                "condition": condition,
                "evaluateOver": "the standard 5-minute window",
            },
            "mechanism": (
                f"AppDynamics Health Rule (metric path + condition), not a query; replace "
                f"<tier>/<business-transaction> with the BT serving {scope}. AppD has no "
                f"multi-window error-budget burn-rate — this is a static/baseline threshold"
            ),
        }
    }


_BURN_ADAPTERS: dict[str, Callable[[BurnRateIntent], dict]] = {
    "prometheus": _prometheus_burn,
    "splunk": _splunk_burn,
    "wavefront": _wavefront_burn,
    "appdynamics": _appdynamics_burn,
}
_LOG_ADAPTERS: dict[str, Callable[[LogPatternIntent], dict]] = {
    "prometheus": _prometheus_log,
    "splunk": _splunk_log,
}


def _tools(tools: tuple[str, ...] | None) -> tuple[str, ...]:
    return tools if tools is not None else DEFAULT_ALERT_TOOLS


def render_burn_rate(intent: BurnRateIntent, tools: tuple[str, ...] | None = None) -> dict:
    """Render a burn-rate intent into an `expr` dict across the selected backends."""
    expr: dict = {}
    for t in _tools(tools):
        if t in _BURN_ADAPTERS:
            expr.update(_BURN_ADAPTERS[t](intent))
    expr["windows"] = _WINDOWS_LABEL
    return expr


def render_log_pattern(intent: LogPatternIntent, tools: tuple[str, ...] | None = None) -> dict:
    """Render a log-pattern intent into an `expr` dict across the selected backends."""
    expr: dict = {}
    for t in _tools(tools):
        if t in _LOG_ADAPTERS:
            expr.update(_LOG_ADAPTERS[t](intent))
    return expr


# Map each `expr` key back to its backend, so an artifact can honestly report which backends it
# actually rendered for (AlertIntent.renderTargets) — a key with a None value (e.g. log-pattern has
# no Prometheus metric) does not count as rendered.
_KEY_BACKEND = {
    "prometheus_fast": "prometheus", "prometheus_slow": "prometheus", "prometheus": "prometheus",
    "splunk": "splunk",
    "wavefront": "wavefront", "wavefront_fast": "wavefront", "wavefront_slow": "wavefront",
    "appdynamics": "appdynamics",
}


def rendered_targets(expr: dict) -> list[str]:
    """The backends an `expr` dict was actually rendered for, in stable order."""
    out: list[str] = []
    for key, val in expr.items():
        backend = _KEY_BACKEND.get(key)
        if backend and val is not None and backend not in out:
            out.append(backend)
    return out
