"""Timeout/retry-budget check: flag downstream timeouts that exceed the flow's SLO
budget (a real, hard-to-eyeball reliability bug). Deterministic; feeds ReadinessScore."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, FactSet
from sre_kb.util import parse_duration_ms


def _slo_budget_ms(fs: FactSet) -> int | None:
    budgets: list[int] = []
    for f in fs.of("config.slo"):
        for token in str(f.attrs.get("buckets", "")).strip("[]").split(","):
            ms = parse_duration_ms(token.strip())
            if ms:
                budgets.append(ms)
    return max(budgets) if budgets else None


def collect(ctx: ScanContext, fs: FactSet) -> list[Fact]:
    budget = _slo_budget_ms(fs)
    if budget is None:
        return []
    out: list[Fact] = []
    for f in fs.of("config.client"):
        t = parse_duration_ms(f.attrs.get("timeout"))
        if t and t > budget:
            out.append(
                Fact(
                    "budget.finding",
                    {
                        "kind": "timeout-exceeds-slo",
                        "subject": f"client '{f.attrs.get('client')}'",
                        "timeoutMs": t,
                        "budgetMs": budget,
                        "detail": f"client '{f.attrs.get('client')}' timeout {f.attrs.get('timeout')} "
                        f"exceeds flow SLO budget {budget}ms — one slow call can blow the SLO",
                    },
                    f.evidence,
                )
            )
    for f in fs.of("config.timelimiter"):
        t = parse_duration_ms(f.attrs.get("timeout"))
        if t and t > budget:
            out.append(
                Fact(
                    "budget.finding",
                    {
                        "kind": "timeout-exceeds-slo",
                        "subject": f"timelimiter '{f.attrs.get('instance')}'",
                        "timeoutMs": t,
                        "budgetMs": budget,
                        "detail": f"timelimiter '{f.attrs.get('instance')}' {f.attrs.get('timeout')} "
                        f"exceeds flow SLO budget {budget}ms",
                    },
                    f.evidence,
                )
            )
    return out
