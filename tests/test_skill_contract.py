"""Skill ↔ engine contract: the field shapes the skill references promise must match what
the engine actually emits.

The skills tell Copilot (and on-call humans) to read specific artifact fields —
`BlastRadius.containment`, `dependencyCriticality`, `Runbook.spec.trigger.alertRef`, etc. If
the engine renames or restructures one of those, the skill silently sends the reader to a
field that no longer exists. This test runs a real scan + estate and asserts every field the
skill docs promise is present in at least one emitted artifact of that kind, so drift fails
CI instead of misleading a reader during enrichment or an incident.

If you intentionally rename a field, update both this contract and the skill reference that
documents it — they are meant to move together."""

from __future__ import annotations

from pathlib import Path

import pytest

from sre_kb.estate import run_estate
from sre_kb.pipeline import run as run_pipeline
from sre_kb.render import load_kb

FIXTURES = Path(__file__).parent / "fixtures"

# The contract: dotted spec paths each skill reference tells the reader to consult. A field is
# satisfied if it appears in *any* emitted artifact of that kind (some are conditional —
# `stateful` only on data-losing nodes, `coTenancy`/`impactedServices` only on estate runs).
CONTRACT: dict[str, set[str]] = {
    # sre-blast-radius/references/blast-fields.md
    "BlastRadius": {
        "node.type", "node.name", "impactedFlows", "impactedServices", "containment",
        "coTenancy", "stateful.dataLossRisk", "dependencyCriticality", "severityHint",
        "riskRationale",
    },
    # sre-prr-review/references/prr-checks.md
    "ReadinessScore": {"prrChecks", "score", "grade", "coverage", "gaps"},
    # sre-estate/references/estate-fields.md
    "Topology": {"nodes", "edges"},
    # sre-incident-response/references/kb-layout.md
    "Runbook": {
        "trigger.alertRef", "relatedFlow", "symptoms", "diagnosis", "remediation",
        "escalation", "banner",
    },
    "Alert": {"alertType", "signalSource", "severity", "expr"},
}


def _dotted_keys(spec: dict) -> set[str]:
    """Top-level spec keys plus one level of nesting (node.type, stateful.dataLossRisk).
    For lists of dicts (containment, coTenancy, edges) we descend into the first item."""
    keys: set[str] = set()
    for key, value in spec.items():
        keys.add(key)
        child = value[0] if isinstance(value, list) and value and isinstance(value[0], dict) else value
        if isinstance(child, dict):
            keys.update(f"{key}.{sub}" for sub in child)
    return keys


@pytest.fixture(scope="module")
def emitted(tmp_path_factory) -> dict[str, set[str]]:
    work = tmp_path_factory.mktemp("contract")
    run_pipeline(str(FIXTURES / "sample-spring-pcf"), work_root=str(work), run_id="c", to_stage="publish")
    run_estate(
        [str(FIXTURES / "sample-spring-pcf"), str(FIXTURES / "sample-billing-pcf")],
        work_root=str(work), run_id="ce",
    )
    by_kind: dict[str, set[str]] = {}
    for run in ("c", "ce"):
        for doc in load_kb(work / run):
            by_kind.setdefault(doc["kind"], set()).update(_dotted_keys(doc.get("spec", {})))
    return by_kind


@pytest.mark.parametrize("kind", sorted(CONTRACT))
def test_skill_promised_fields_are_emitted(kind: str, emitted: dict[str, set[str]]):
    seen = emitted.get(kind, set())
    assert seen, f"no {kind} artifact emitted — cannot verify the skill contract"
    missing = CONTRACT[kind] - seen
    assert not missing, f"{kind}: skills reference field(s) the engine no longer emits: {sorted(missing)}"
