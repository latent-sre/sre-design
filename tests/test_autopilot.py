"""Autopilot: the scan → provider → apply → re-scan convergence loop, end-to-end over the fixture
with a stubbed provider. Every kept output must arrive through the same deterministic gates the
manual loop uses — re-grounded proposals, monotonic verdicts, needs-review drafts."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from sre_kb.pipeline.autopilot import run_autopilot
from sre_kb.workspace import RunLayout

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"

# Verbatim fixture lines the stub quotes back as anchors — read at test time so the test can't
# drift from the fixture bytes.
_PUBLISH_LINE = (FIXTURE / "src/main/java/com/acme/order/events/OrderEventPublisher.java") \
    .read_text().splitlines()[23].strip()
_WARN_LOG_LINE = (FIXTURE / "src/main/java/com/acme/order/client/InventoryClient.java") \
    .read_text().splitlines()[29].strip()

_UNCOVERED_RE = re.compile(r"^- (\S+)\s+severity=", re.M)


class StubProvider:
    id = "stub"
    interactive = False

    def complete(self, prompt: str) -> str:
        if "Gap-finder context" in prompt:
            return json.dumps({"proposals": [
                {"category": "data-loss-path", "target": "orders-postgres", "severity": "high",
                 "anchor": _PUBLISH_LINE, "rationale": "publish failure is swallowed — order lost"},
            ]})
        if "Alert-draft context" in prompt:
            return json.dumps({"proposals": [
                {"anchor": _WARN_LOG_LINE, "severity": "medium",
                 "rationale": "the inventory fallback engaging means reservations are degraded"},
            ]})
        if "Runbook-draft context" in prompt:
            m = _UNCOVERED_RE.search(prompt)
            if not m:
                return '{"proposals": []}'
            return json.dumps({"proposals": [
                {"alertRef": m.group(1), "symptoms": ["latency burn on order creation"],
                 "diagnosis": ["inspect recent deploys"], "remediation": ["scale within limits"],
                 "escalation": "platform on-call"},
            ]})
        if "Architecture-draft context" in prompt:
            return json.dumps({"proposals": [
                {"pattern": "event-notification", "anchor": _PUBLISH_LINE,
                 "rationale": "publishes a domain event after the write"},
            ]})
        if "deployment-review context" in prompt:
            return json.dumps({"proposals": [
                {"check": "missing-disk-quota", "app": "order-service", "severity": "low",
                 "rationale": "no disk_quota declared for an app that writes local spill files"},
            ]})
        if "Coverage-discovery context" in prompt:
            return '{"areas": []}'
        if "Diagram-narration context" in prompt:
            return json.dumps({"narrations": [
                {"diagram": "create-order", "text": "Shows the create-order flow."},
                {"diagram": "no-such-drawing", "text": "must be dropped"},
            ]})
        if "allowedRefs" in prompt:  # the narrative brief
            return "Risk is concentrated in the publish path; review the uncovered burn-rate alert."
        if "Affirm" in prompt:
            return "affirm"
        return "supported: fine"

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)


def test_autopilot_converges_and_folds_every_channel_in(tmp_path):
    target = tmp_path / "target"
    shutil.copytree(FIXTURE, target)
    result = run_autopilot(str(target), StubProvider(),
                           work_root=str(tmp_path / "work"), run_base="ap", cycles=2)

    assert result.run_id == "ap-c2"
    assert [c.run_id for c in result.cycles] == ["ap-c1", "ap-c2"]
    assert all(t["status"] == "written" for c in result.cycles for t in c.tasks), result.cycles
    assert all(c.confirm_outcomes > 0 for c in result.cycles)  # boundary calls were adjudicated

    layout = RunLayout(tmp_path / "work", "ap-c2")
    # cycle 2's scan re-grounded cycle 1's gap proposal -> a routed needs-review ResiliencyGap
    gaps = list((layout.kb / "needs-review").rglob("ResiliencyGap/*data-loss-path*.yaml"))
    assert gaps, "the re-grounded gap proposal should land in the final run's KB"
    # the drafted Tier-B alert + runbook were folded into the final KB, needs-review only
    assert result.drafted_alerts == 1
    assert list((layout.kb / "needs-review").rglob("Alert/*log-alert*.yaml"))
    assert result.drafted_runbooks == 1
    assert (layout.kb / "needs-review" / "Runbook" / "create-order-latency-burn-rate.yaml").exists()
    assert result.proposed_patterns == 1
    # the PCF review proposal was folded in and REFUTED by the manifest bytes — the fixture
    # declares disk_quota: 1G, so the claim dies at the engine's re-derivation gate
    assert result.pcf_review_routed == 0
    import json as _json
    review = _json.loads((target / ".sre" / "pcf-review.json").read_text())
    assert review["findings"] == []
    # the valid narration decorated the rendered diagram; the bogus name was dropped
    assert result.narrations_applied == 1
    flow_md = (layout.root / "projections" / "diagrams" / "create-order.md").read_text()
    assert "Narration (LLM, advisory)" in flow_md
    assert list((layout.kb / "needs-review").rglob("Architecture/*proposed-patterns*.yaml"))
    assert not list((layout.kb / "verified").rglob("Runbook/create-order-latency-burn-rate.yaml"))
    # the narrative was grounded and rendered into the run's reports
    assert result.narrative_note and "resolve" in result.narrative_note
    rendered = (layout.reports / "findings-narrative.md").read_text()
    assert "Tier-B advisory" in rendered and "publish path" in rendered


def test_autopilot_supported_verdicts_never_promote(tmp_path):
    """The provider answering 'supported' to every challenge changes nothing — the loop is
    downgrade-only end to end."""
    target = tmp_path / "target"
    shutil.copytree(FIXTURE, target)
    result = run_autopilot(str(target), StubProvider(),
                           work_root=str(tmp_path / "work"), run_base="np", cycles=1)
    assert all(c.challenge_changed == 0 for c in result.cycles)


def test_cli_autopilot_without_oracle_defers(tmp_path):
    from typer.testing import CliRunner

    from sre_kb.cli import app

    res = CliRunner().invoke(
        app, ["autopilot", "--target", str(FIXTURE), "--work-root", str(tmp_path)],
        env={"SRE_KB_ORACLE": ""},
    )
    assert res.exit_code == 0
    assert "manual loop" in res.stdout
    assert not list(tmp_path.iterdir())  # no run was started without a provider
