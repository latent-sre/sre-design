"""Substance gate: schema-valid but operationally empty artifacts must not stay verified."""

from sre_kb.validation.substance import check_substance


def _alert(expr):
    return {"kind": "Alert", "metadata": {"name": "x"}, "spec": {"expr": expr}}


def test_alert_without_expression_is_flagged():
    assert check_substance(_alert({})) == ["alert-without-expression"]
    null_backends = _alert({"prometheus": None, "splunk": None})
    assert check_substance(null_backends) == ["alert-without-expression"]
    meta_only = _alert({"windows": "multi-window"})
    assert check_substance(meta_only) == ["alert-without-expression"]


def test_alert_with_a_real_expression_passes():
    assert check_substance(_alert({"prometheus_fast": "sum(rate(...))"})) == []
    assert check_substance(_alert({"wavefront": {"query": "ts(...)"}})) == []


def _slo(objectives):
    return {"kind": "SloSli", "metadata": {"name": "x"}, "spec": {"objectives": objectives}}


def test_slo_without_target_is_flagged():
    assert check_substance(_slo([{"sli": "latency"}])) == ["slo-objective-without-target"]
    null_target = _slo([{"sli": "latency", "target": None}])
    assert check_substance(null_target) == ["slo-objective-without-target"]


def test_slo_with_a_target_passes():
    assert check_substance(_slo([{"sli": "latency", "target": 99.5}])) == []


def test_other_kinds_are_not_flagged():
    assert check_substance({"kind": "Runbook", "spec": {}}) == []
