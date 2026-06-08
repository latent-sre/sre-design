"""Observability collector: every logback appender <pattern> is captured, each citing its own lines."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.java_spring import observability

_LOGBACK = """\
<configuration>
  <appender name="console" class="ch.qos.logback.core.ConsoleAppender">
    <encoder><pattern>%d %X{traceId} %-5level %logger - %msg%n</pattern></encoder>
  </appender>
  <appender name="file" class="ch.qos.logback.core.FileAppender">
    <encoder><pattern>%d %X{requestId} %X{spanId} %msg%n</pattern></encoder>
  </appender>
</configuration>
"""


def test_every_appender_pattern_is_collected_with_its_own_lines(tmp_path):
    """Regression: only the first <pattern> used to be collected; a console+file logback dropped one."""
    (tmp_path / "logback-spring.xml").write_text(_LOGBACK, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")

    facts = [f for f in observability.collect(ctx) if f.type == "observability.logging"]
    assert len(facts) == 2                                            # both appenders captured
    fields = {tuple(f.attrs["correlationFields"]) for f in facts}
    assert ("traceId",) in fields and ("requestId", "spanId") in fields
    # each fact cites a distinct line (its own <pattern> block), not the first occurrence
    assert len({f.evidence.lines.start for f in facts}) == 2
