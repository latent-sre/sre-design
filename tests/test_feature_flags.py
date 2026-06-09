"""FeatureFlag detector (coverage matrix #15): config blocks, @ConditionalOnProperty, flag-SDK calls."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common import feature_flags
from sre_kb.synth.scaffold import scaffold

FIXTURE = Path(__file__).parent / "fixtures" / "sample-feature-flags"


def _flags():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-feature-flags")
    return {f.attrs["name"]: f.attrs for f in feature_flags.collect(ctx)}


def test_all_three_sources_detected():
    flags = _flags()
    # config block (booleans), @ConditionalOnProperty, and an SDK call
    assert set(flags) == {"new-checkout", "kill-switch-payments", "features.beta-search", "new-pricing"}
    assert flags["new-checkout"]["provider"] == "config" and flags["new-checkout"]["defaultState"] == "off"
    assert flags["features.beta-search"]["provider"] == "spring-config"
    assert flags["features.beta-search"]["defaultState"] == "off"   # matchIfMissing=false
    assert flags["new-pricing"]["provider"] == "launchdarkly"
    assert flags["new-pricing"]["defaultState"] == "unknown"        # default is a runtime arg


def test_kill_switch_heuristic():
    flags = _flags()
    assert flags["kill-switch-payments"]["killSwitch"] is True
    assert flags["new-checkout"]["killSwitch"] is False


def test_flags_are_byte_grounded():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-feature-flags")
    for f in feature_flags.collect(ctx):
        assert f.evidence.detector == "common.feature_flags"
        assert f.evidence.source_tier == "ast"


def test_scaffolds_verified_featureflag_artifacts():
    ctx = ScanContext(root=FIXTURE, repo="file://sample-feature-flags")
    docs = scaffold(scan(ctx), ctx)
    ff = {d["metadata"]["name"]: d for d in docs if d["kind"] == "FeatureFlag"}
    assert "kill-switch-payments" in ff
    assert ff["kill-switch-payments"]["status"] == "verified"
    assert ff["kill-switch-payments"]["spec"]["killSwitch"] is True


def test_go_sdk_flag_call_is_detected(tmp_path):
    # Go calls carried no string args, so the *.go glob in _sdk_flags was dead code.
    (tmp_path / "main.go").write_text(
        'package main\n\nfunc f() {\n\ton := ldclient.BoolVariation("new-checkout", user, false)\n\t_ = on\n}\n',
        encoding="utf-8",
    )
    ctx = ScanContext(root=tmp_path, repo="file://x")
    flags = {f.attrs["name"]: f.attrs for f in feature_flags.collect(ctx)}
    assert flags["new-checkout"]["provider"] == "launchdarkly"
    assert flags["new-checkout"]["defaultState"] == "unknown"


def test_self_gating_on_a_plain_repo(tmp_path):
    (tmp_path / "Plain.java").write_text("package x;\npublic class Plain {}\n", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    assert feature_flags.collect(ctx) == []
