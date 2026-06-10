"""Build collector: each dependency fact cites its own <artifactId> line, not a name-collision."""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.java_spring import build

# `widget-core` also appears in a <groupId> ABOVE the (whitespace-wrapped) <artifactId>, so the old
# `find_line(name)` fallback mis-cited the groupId line; the match offset cites the artifactId.
_POM = """\
<project>
  <dependencies>
    <dependency>
      <groupId>widget-core</groupId>
      <artifactId>
        widget-core
      </artifactId>
    </dependency>
  </dependencies>
</project>
"""


def test_dependency_cites_its_artifactid_not_a_name_collision(tmp_path):
    (tmp_path / "pom.xml").write_text(_POM, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    dep = next(f for f in build.collect(ctx) if f.attrs.get("name") == "widget-core")

    cited = _POM.splitlines()[dep.evidence.lines.start - 1]
    assert "<artifactId>" in cited and "<groupId>" not in cited


def test_dependency_captures_group_and_version_when_adjacent(tmp_path):
    """Canonical pom order (groupId, artifactId, version) yields group/version attrs; a bare
    artifactId still emits a fact with just the name."""
    (tmp_path / "pom.xml").write_text(
        "<project><dependencies>\n"
        "<dependency>\n  <groupId>com.acme</groupId>\n  <artifactId>acme-models</artifactId>\n"
        "  <version>1.2.3</version>\n</dependency>\n"
        "<dependency>\n  <artifactId>bare</artifactId>\n</dependency>\n"
        "</dependencies></project>\n",
        encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    deps = {f.attrs["name"]: f.attrs for f in build.collect(ctx) if f.type == "tech.dependency"}
    assert deps["acme-models"] == {"name": "acme-models", "group": "com.acme", "version": "1.2.3"}
    assert deps["bare"] == {"name": "bare"}
