"""Compute BlastRadius risk from real factors instead of a per-node-type lookup table.

Two axes that the old code conflated are kept separate:

  - criticality: the consequence to the impacted flows if the dependency fails.
      critical  no bulkhead — a failure fails the flow, or loses data
      degraded  a circuit breaker / fallback lets the flow continue in a degraded mode

  - severity:    overall blast, which now SCALES with how many flows are hit (this is what
                 multiplicity unlocked) and whether the failure is irreversible (data loss).

Containment (the bulkhead mechanisms) is reported separately in the spec, not folded into
criticality — a circuit breaker isolates cascading failure, it does not make a dependency
unimportant. `assess` returns a one-line rationale so the number is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeRisk:
    severity: str  # medium | high — a dependency big enough to model is never "low" blast (see below)
    criticality: str  # critical | degraded
    rationale: str


def assess(*, impacted_flows: int, data_loss: bool, contained: bool) -> NodeRisk:
    flows = max(1, impacted_flows)
    criticality = "degraded" if (contained and not data_loss) else "critical"

    score = 0
    if data_loss:
        score += 3  # irreversible
    if not contained:
        score += 3  # no bulkhead: a failure takes the flow down
    if contained:
        score += 1  # a degraded flow is still a concern
    score += min(2, flows - 1)  # breadth: +1 at 2 flows, +2 at 3+

    # score is always >= 1 (an uncontained dep adds 3, a contained one adds 1), so a modelled
    # dependency floors at "medium" by design — "low" is unreachable and intentionally not emitted.
    severity = "high" if score >= 3 else "medium"

    why = [f"{flows} impacted flow{'s' if flows != 1 else ''}"]
    if data_loss:
        why.append("irreversible data loss on failure")
    elif not contained:
        why.append("no bulkhead — a failure fails the flow")
    else:
        why.append("behind a circuit breaker / fallback")
    return NodeRisk(severity, criticality, f"severity={severity}: " + ", ".join(why))
