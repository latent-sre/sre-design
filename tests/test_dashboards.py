"""Dashboard kind + RED panel generation (HYBRID-PLAN Phase 5 / §9.6, adopted from resiliency-skills).

The Dashboard artifact is scaffolded with deterministic Prometheus queries (RED: rate/errors/
duration) scoped to the flow's route, lands needs-review (a suggested dashboard) + unverified-against-
live, and validates against the adopted schema on our byte-grounded envelope.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.pipeline import run as run_pipeline
from sre_kb.render.dashboards import red_panels
from sre_kb.validation import validate_kb_tree

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def test_red_panels_are_deterministic_prometheus_queries():
    panels = red_panels("/api/v1/orders", percentile="p99")
    titles = [p["title"] for p in panels]
    assert titles == ["Request rate", "Error fraction", "Latency p99"]
    by_title = {p["title"]: p for p in panels}
    assert by_title["Request rate"]["signal"]["query"] == \
        'sum(rate(http_server_requests_seconds_count{uri="/api/v1/orders"}[5m]))'
    assert 'outcome!="SUCCESS"' in by_title["Error fraction"]["signal"]["query"]
    assert by_title["Latency p99"]["signal"]["query"].startswith("histogram_quantile(0.99,")
    assert all(p["signal"]["source"] == "prometheus" for p in panels)


def test_unknown_source_emits_no_fabricated_query():
    panels = red_panels("/x", source="grafana")
    assert all("query" not in p["signal"] for p in panels)  # honest: no dialect we can't generate
    assert all(p["signal"]["metric"] for p in panels)        # still names the metric


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    work = tmp_path_factory.mktemp("dashwork")
    return run_pipeline(str(FIXTURE), work_root=str(work), run_id="d", to_stage="validate")


def test_run_emits_a_dashboard(result):
    docs = {}
    for p in (result.root / "kb").rglob("*.yaml"):
        d = yaml.safe_load(p.read_text())
        docs[(d["kind"], d["metadata"]["name"])] = d
    dash = docs[("Dashboard", "order-service-overview")]
    assert dash["status"] == "needs-review"          # a suggested dashboard, never auto-verified
    assert dash["unverifiedAgainstLive"] is True
    assert [p["title"] for p in dash["spec"]["panels"]] == \
        ["Request rate", "Error fraction", "Latency p99"]
    assert dash["spec"]["renderTarget"] == "prometheus"
    # the whole KB (including the new kind) still validates structurally + provenance
    assert not [r for r in validate_kb_tree(result.root / "kb") if not r.ok]
