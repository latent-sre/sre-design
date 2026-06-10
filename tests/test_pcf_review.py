"""Tier-B PCF deployment review (§3.2): the engine re-derives every accepted check from the
manifest bytes — a proposal the manifest disproves is refuted regardless of its rationale."""

from __future__ import annotations

import json

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common import manifest_pcf
from sre_kb.pipeline.pcf_review import (
    PROPOSALS_REL,
    REVIEW_REL,
    PcfProposal,
    apply_review,
    run_pcf_review,
)

_MANIFEST = """\
applications:
- name: orders
  instances: 1
  memory: 1G
  routes:
  - route: orders.apps.internal
  env:
    INVENTORY_API_URL: http://inventory.apps.internal
- name: worker
  instances: 4
  disk_quota: 2G
  no-route: true
  health-check-type: process
"""


def _apps(tmp_path):
    (tmp_path / "manifest.yml").write_text(_MANIFEST, encoding="utf-8")
    return manifest_pcf.collect(ScanContext(root=tmp_path, repo="file://x"))


def test_rederivation_keeps_only_what_the_manifest_proves(tmp_path):
    apps = [f for f in _apps(tmp_path) if f.type == "pcf.app"]
    result = apply_review(apps, [
        PcfProposal("single-instance", "orders", "high", "no failover"),       # true: 1 instance
        PcfProposal("single-instance", "worker"),                              # false: 4 instances
        PcfProposal("port-health-check", "orders"),                            # true: unset + routes
        PcfProposal("port-health-check", "worker"),                            # false: no-route app
        PcfProposal("missing-disk-quota", "orders"),                           # true
        PcfProposal("missing-disk-quota", "worker"),                           # false: 2G declared
        PcfProposal("env-config-binding", "orders"),                           # true: *_API_URL env
        PcfProposal("made-up-check", "orders"),                                # vocabulary miss
        PcfProposal("single-instance", "ghost"),                               # no such app
    ])
    by = {(o.proposal.check, o.proposal.app): o.result for o in result.outcomes}
    assert by[("single-instance", "orders")] == "routed"
    assert by[("single-instance", "worker")] == "refuted"
    assert by[("port-health-check", "orders")] == "routed"
    assert by[("port-health-check", "worker")] == "refuted"
    assert by[("missing-disk-quota", "orders")] == "routed"
    assert by[("missing-disk-quota", "worker")] == "refuted"
    assert by[("env-config-binding", "orders")] == "routed"
    assert by[("made-up-check", "orders")] == "unknown-check"
    assert by[("single-instance", "ghost")] == "unknown-app"
    assert all(o.path == "manifest.yml" for o in result.kept())


def test_run_pcf_review_writes_advisory_findings(tmp_path):
    (tmp_path / "manifest.yml").write_text(_MANIFEST, encoding="utf-8")
    (tmp_path / ".sre").mkdir()
    (tmp_path / PROPOSALS_REL).write_text(json.dumps({"proposals": [
        {"check": "single-instance", "app": "orders", "severity": "high",
         "rationale": "an HTTP app with one instance has no failover"},
        {"check": "single-instance", "app": "worker", "severity": "high",
         "rationale": "wrong — the engine must drop this"},
    ]}), encoding="utf-8")
    result = run_pcf_review(str(tmp_path))
    assert len(result.kept()) == 1
    review = json.loads((tmp_path / REVIEW_REL).read_text())
    assert len(review["findings"]) == 1
    f = review["findings"][0]
    assert f["check"] == "single-instance" and f["app"] == "orders"
    assert f["source"] == "llm" and f["advisory"] is True
    assert f["evidence"] == "manifest.yml"


def test_missing_or_garbage_proposals_are_a_noop(tmp_path):
    (tmp_path / "manifest.yml").write_text(_MANIFEST, encoding="utf-8")
    result = run_pcf_review(str(tmp_path))  # no proposals file
    assert result.outcomes == []
    (tmp_path / ".sre").mkdir(exist_ok=True)
    (tmp_path / PROPOSALS_REL).write_text("not json", encoding="utf-8")
    assert run_pcf_review(str(tmp_path)).outcomes == []


def test_omitted_instances_defaults_to_one_and_routes(tmp_path):
    """Cloud Foundry defaults instances to 1 when the key is omitted — a single-instance
    proposal for such an app must route, not be refuted with 'instances=None'."""
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: solo\n  routes:\n  - route: solo.apps.internal\n",
        encoding="utf-8")
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.common import manifest_pcf

    apps = [f for f in manifest_pcf.collect(ScanContext(root=tmp_path, repo="file://x"))
            if f.type == "pcf.app"]
    result = apply_review(apps, [PcfProposal("single-instance", "solo", "high", "no failover")])
    assert result.outcomes[0].result == "routed"


def test_env_variant_condition_is_rederived_not_refuted_by_the_base(tmp_path):
    """manifest-prod.yml overriding instances: 1 is a real prod risk even when manifest.yml
    declares 3 — re-derivation must consider every manifest fact for the app."""
    (tmp_path / "manifest.yml").write_text(
        "applications:\n- name: orders\n  instances: 3\n", encoding="utf-8")
    (tmp_path / "manifest-prod.yml").write_text(
        "applications:\n- name: orders\n  instances: 1\n", encoding="utf-8")
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.common import manifest_pcf

    apps = [f for f in manifest_pcf.collect(ScanContext(root=tmp_path, repo="file://x"))
            if f.type == "pcf.app"]
    result = apply_review(apps, [PcfProposal("single-instance", "orders", "high", "prod risk")])
    [o] = result.outcomes
    assert o.result == "routed"
    assert "prod" in o.note  # the proving manifest is named
