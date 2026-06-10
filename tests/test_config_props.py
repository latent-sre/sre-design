"""Spring config collector: each emitted config.* fact must cite its OWN defining line."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.java_spring import config_props


def test_malformed_yaml_emits_a_grounded_parse_error_fact(tmp_path):
    """An unparseable config is recorded as a collector.parse_error fact (auditable coverage gap),
    not silently dropped."""
    (tmp_path / "application.yml").write_text("clients:\n  a: : : oops\n", encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")

    errs = [f for f in config_props.collect(ctx) if f.type == "collector.parse_error"]
    assert len(errs) == 1
    assert errs[0].attrs["detector"] == "java_spring.config_props"
    assert errs[0].evidence.path == "application.yml"   # cites the offending file

_YML = """\
resilience4j:
  timelimiter:
    instances:
      orderClient:
        timeoutDuration: 2s
      paymentClient:
        timeoutDuration: 5s
"""


def test_timelimiter_instances_cite_distinct_lines(tmp_path):
    """Regression: every timelimiter instance used to cite the FIRST timeoutDuration line."""
    (tmp_path / "application.yml").write_text(_YML, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")

    tl = [f for f in config_props.collect(ctx) if f.type == "config.timelimiter"]
    by_instance = {f.attrs["instance"]: f for f in tl}
    assert set(by_instance) == {"orderClient", "paymentClient"}

    order_ln = by_instance["orderClient"].evidence.lines.start
    payment_ln = by_instance["paymentClient"].evidence.lines.start
    assert order_ln != payment_ln                      # distinct, not both the first occurrence
    lines = _YML.splitlines()
    assert "2s" in lines[order_ln - 1]                 # orderClient cites its own 2s line
    assert "5s" in lines[payment_ln - 1]               # paymentClient cites its own 5s line


def test_config_import_emits_external_source_facts(tmp_path):
    """spring.config.import entries (with/without optional:) and the legacy
    spring.cloud.config.uri all surface as config.source facts citing their lines."""
    (tmp_path / "application.yml").write_text(
        "spring:\n"
        "  config:\n"
        "    import:\n"
        "    - optional:configserver:http://config.internal:8888\n"
        "    - vault://secret/orders\n"
        "  cloud:\n"
        "    config:\n"
        "      uri: http://legacy-config:8888\n",
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    srcs = [f for f in config_props.collect(ctx) if f.type == "config.source"]
    by_kind = {(f.attrs["kind"], f.attrs["uri"]): f.attrs for f in srcs}
    assert by_kind[("configserver", "http://config.internal:8888")]["optional"] is True
    assert ("vault", "//secret/orders") in by_kind
    assert by_kind[("configserver", "http://legacy-config:8888")]["optional"] is False
    assert all(f.evidence.path == "application.yml" for f in srcs)
