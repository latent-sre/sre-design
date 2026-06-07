"""Substance lint: an artifact can be schema-valid yet operationally empty — an Alert with no
expression, or an SLO objective with no target. The schema gates *structure*; this gates
*substance*. A hit downgrades the artifact to needs-review (monotonic, like the safety lint) so a
human supplies the missing content before it can count as verified."""

from __future__ import annotations

_ALERT_EXPR_META = {"windows"}  # descriptive metadata in expr, not an executable expression


def check_substance(doc: dict) -> list[str]:
    """Return names of substance gaps in the artifact's spec ([] = has substance)."""
    kind, spec = doc.get("kind"), doc.get("spec") or {}
    gaps: list[str] = []
    if kind == "Alert":
        expr = spec.get("expr") or {}
        if not any(k not in _ALERT_EXPR_META and v for k, v in expr.items()):
            gaps.append("alert-without-expression")
    elif kind == "SloSli":
        objectives = spec.get("objectives") or []
        if not any(o.get("target") is not None for o in objectives):
            gaps.append("slo-objective-without-target")
    return gaps
