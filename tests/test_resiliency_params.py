"""Tier-A parameter-completeness gaps (HYBRID-PLAN Round-3 R5).

A resilience pattern declared but missing its load-bearing param is a deterministic, byte-grounded
gap: a @CircuitBreaker with no failure-rate-threshold, a @Retry with no wait-duration/backoff. The
resolver honours resilience4j config layering (instance, base-config, implicit configs.default).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from sre_kb.collectors.base import LOCAL_COMMIT, ScanContext
from sre_kb.collectors.java_spring import resiliency_params
from sre_kb.pipeline import run as run_pipeline

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"

# application.yml with the SLO/clients/management kept but the resilience4j block removed, so the
# sample's @CircuitBreaker(inventory) becomes unconfigured.
_NO_RESILIENCE_YML = """\
spring:
  application:
    name: order-service
clients:
  inventory:
    base-url: http://inventory-service.apps.internal
    timeout: 3s
management:
  endpoints:
    web:
      exposure:
        include: health,info,prometheus
  metrics:
    distribution:
      slo:
        http.server.requests: 200ms,500ms,800ms
"""


def _ctx(root: Path) -> ScanContext:
    return ScanContext(root=root, repo=f"file://{root.name}", commit=LOCAL_COMMIT)


def _gaps(tmp_path: Path, java: str, yml: str) -> set[tuple[str, str]]:
    (tmp_path / "C.java").write_text(java, encoding="utf-8")
    (tmp_path / "application.yml").write_text(yml, encoding="utf-8")
    return {
        (f.attrs["category"], f.attrs["target"]) for f in resiliency_params.collect(_ctx(tmp_path))
    }


# --------------------------------------------------------------------------- the detector (unit)


def test_unconfigured_patterns_gap_configured_ones_do_not(tmp_path):
    java = """\
package com.acme;
class C {
  @CircuitBreaker(name = "cbok")
  String a() { return ""; }
  @CircuitBreaker(name = "cbbase")
  String b() { return ""; }
  @CircuitBreaker(name = "cbgap")
  String c() { return ""; }
  @Retry(name = "retryok")
  String d() { return ""; }
  @Retry(name = "retrystorm")
  String e() { return ""; }
}
"""
    yml = """\
resilience4j:
  circuitbreaker:
    configs:
      shared:
        failureRateThreshold: 60
    instances:
      cbok:
        failureRateThreshold: 50
      cbbase:
        base-config: shared
  retry:
    instances:
      retryok:
        waitDuration: 500ms
"""
    assert _gaps(tmp_path, java, yml) == {
        ("circuit-breaker-without-thresholds", "cbgap"),
        ("retry-without-backoff", "retrystorm"),
    }


def test_implicit_default_config_covers_an_instance(tmp_path):
    # An instance with no base-config inherits configs.default -> configured -> no gap.
    java = 'package com.acme;\nclass C {\n  @CircuitBreaker(name = "x")\n  String a() { return ""; }\n}\n'
    yml = "resilience4j:\n  circuitbreaker:\n    configs:\n      default:\n        failureRateThreshold: 50\n"
    assert _gaps(tmp_path, java, yml) == set()


def test_explicit_base_config_overrides_the_default(tmp_path):
    # x points at base-config 'bare' (no threshold); the default does NOT apply -> still a gap.
    java = 'package com.acme;\nclass C {\n  @CircuitBreaker(name = "x")\n  String a() { return ""; }\n}\n'
    yml = """\
resilience4j:
  circuitbreaker:
    configs:
      default:
        failureRateThreshold: 50
      bare:
        slidingWindowSize: 10
    instances:
      x:
        base-config: bare
"""
    assert _gaps(tmp_path, java, yml) == {("circuit-breaker-without-thresholds", "x")}


# --------------------------------------------------------------------------- end-to-end via `run`


def _run_copy(tmp_path: Path, *, strip: bool, run_id: str) -> list[dict]:
    target = tmp_path / run_id
    shutil.copytree(FIXTURE, target)
    if strip:
        (target / "src" / "main" / "resources" / "application.yml").write_text(
            _NO_RESILIENCE_YML, encoding="utf-8"
        )
    res = run_pipeline(
        str(target), work_root=str(tmp_path / f"w-{run_id}"), run_id=run_id, to_stage="validate"
    )
    return [yaml.safe_load(p.read_text()) for p in (res.root / "kb").rglob("*.yaml")]


def _cb_gaps(docs: list[dict]) -> list[dict]:
    return [
        d
        for d in docs
        if d["kind"] == "ResiliencyGap"
        and d["spec"]["category"] == "circuit-breaker-without-thresholds"
    ]


def test_param_gap_flows_through_run_as_verified_tier_a(tmp_path):
    # Baseline: the sample's @CircuitBreaker IS configured -> no param-completeness gap.
    assert _cb_gaps(_run_copy(tmp_path, strip=False, run_id="cfg")) == []

    # Strip the resilience4j config -> the breaker is unconfigured -> a verified Tier-A gap.
    gaps = _cb_gaps(_run_copy(tmp_path, strip=True, run_id="nocfg"))
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["spec"]["target"] == "inventory"
    assert gap["status"] == "verified"  # deterministic -> can verify
    assert gap["spec"]["sourceTier"] == "ast"
    assert gap["spec"]["rederivation"] == "param-completeness"
    assert gap["evidence"][0]["detector"] == "java_spring.resiliency_params"
    assert gap["evidence"][0]["source_tier"] == "ast"


# --- S4c proactive disable probe ---------------------------------------------------------------
_JAVA = (
    "package acme;\npublic class C {\n"
    '  @CircuitBreaker(name = "inventory")\n  public String call() { return "x"; }\n}\n'
)


def _disable_gaps(tmp_path, config_yaml):
    (tmp_path / "C.java").write_text(_JAVA, encoding="utf-8")
    (tmp_path / "application.yml").write_text(config_yaml, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    return [f for f in resiliency_params.collect(ctx) if f.type == "resiliency.gap"]


def test_explicitly_disabled_instance_emits_a_proactive_tier_a_gap(tmp_path):
    """S4c graduation: enabled: false in the instance's resolved config emits the
    disabled-resilience gap with no LLM pointing — citing the disabling config line —
    and dominates the parameter gap (tuning a breaker that is off is moot)."""
    gaps = _disable_gaps(tmp_path,
                 "resilience4j:\n  circuitbreaker:\n    instances:\n      inventory:\n"
                 "        enabled: false\n")
    [g] = gaps
    assert g.attrs["category"] == "disabled-resilience"
    assert g.attrs["target"] == "inventory" and g.attrs["rederivation"] == "disabled"
    assert g.evidence.path == "application.yml"
    assert "enabled" in (tmp_path / "application.yml").read_text().splitlines()[g.evidence.lines.start - 1]
    assert g.evidence.source_tier == "ast"  # verified-eligible, the graduation point


def test_disable_inherited_from_default_config_unless_instance_overrides(tmp_path):
    inherited = _disable_gaps(tmp_path,
                      "resilience4j:\n  circuitbreaker:\n    configs:\n      default:\n"
                      "        enabled: false\n    instances:\n      inventory:\n"
                      "        failure-rate-threshold: 50\n")
    assert [g.attrs["category"] for g in inherited] == ["disabled-resilience"]
    overridden = _disable_gaps(tmp_path,
                       "resilience4j:\n  circuitbreaker:\n    configs:\n      default:\n"
                       "        enabled: false\n    instances:\n      inventory:\n"
                       "        enabled: true\n        failure-rate-threshold: 50\n")
    assert overridden == []  # the instance's own toggle decides outright


def test_enabled_instance_keeps_the_param_completeness_behavior(tmp_path):
    gaps = _disable_gaps(tmp_path, "resilience4j:\n  circuitbreaker:\n    instances:\n      inventory:\n"
                           "        enabled: true\n")
    assert [g.attrs["category"] for g in gaps] == ["circuit-breaker-without-thresholds"]
