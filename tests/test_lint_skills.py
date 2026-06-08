"""DEEP-COMPARISON R6: the skill pipeline manifest is canonical and CI-enforced — every skill dir
appears exactly once in .github/skills/pipeline.yaml, and vice-versa. (`tools/lint_skills.py` is the
linter; this wires it into the test suite so the pipeline can't drift.)"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# tools/ is not a package, so load the linter module by path.
_LINT_PATH = Path(__file__).resolve().parents[1] / "tools" / "lint_skills.py"
_spec = importlib.util.spec_from_file_location("lint_skills", _LINT_PATH)
lint_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint_skills)


def test_skill_pipeline_is_clean():
    assert lint_skills.lint() == []  # every skill is in the manifest exactly once


def test_manifest_exists_and_lists_every_skill():
    skills_dir = Path(__file__).resolve().parents[1] / ".github" / "skills"
    dirs = {d.name for d in skills_dir.iterdir() if d.is_dir() and d.name not in lint_skills._RESERVED}
    assert lint_skills.PIPELINE.is_file()
    assert lint_skills._pipeline_skills() == dirs


def test_lint_flags_drift(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "sre-foo").mkdir(parents=True)
    (skills / "sre-foo" / "SKILL.md").write_text(
        "---\nname: sre-foo\ndescription: a test skill description\n---\n", encoding="utf-8"
    )
    (skills / "pipeline.yaml").write_text("phases:\n  map:\n    - sre-bar\n", encoding="utf-8")
    monkeypatch.setattr(lint_skills, "SKILLS", skills)
    monkeypatch.setattr(lint_skills, "PIPELINE", skills / "pipeline.yaml")
    problems = lint_skills.lint()
    assert any("sre-foo" in p for p in problems)  # in skills/ but not the manifest
    assert any("sre-bar" in p for p in problems)  # in the manifest but no skill dir


def _write_skill(skills, fm_body):
    (skills / "sre-foo").mkdir(parents=True, exist_ok=True)
    (skills / "sre-foo" / "SKILL.md").write_text(f"---\n{fm_body}\n---\n", encoding="utf-8")
    (skills / "pipeline.yaml").write_text("phases:\n  map:\n    - sre-foo\n", encoding="utf-8")


def test_lint_requires_allowed_tools(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    _write_skill(skills, "name: sre-foo\ndescription: a test skill description")
    monkeypatch.setattr(lint_skills, "SKILLS", skills)
    monkeypatch.setattr(lint_skills, "PIPELINE", skills / "pipeline.yaml")
    assert any("missing `allowed-tools`" in p for p in lint_skills.lint())


def test_lint_flags_unknown_tool(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    _write_skill(
        skills,
        'name: sre-foo\ndescription: a test skill description\n'
        'allowed-tools: ["codebase", "runCommand"]',  # typo: runCommand vs runCommands
    )
    monkeypatch.setattr(lint_skills, "SKILLS", skills)
    monkeypatch.setattr(lint_skills, "PIPELINE", skills / "pipeline.yaml")
    assert any("unknown tool" in p for p in lint_skills.lint())


def test_lint_bans_top_level_version(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    _write_skill(
        skills,
        'name: sre-foo\nversion: 0.1.0\ndescription: a test skill description\n'
        'allowed-tools: ["codebase"]',
    )
    monkeypatch.setattr(lint_skills, "SKILLS", skills)
    monkeypatch.setattr(lint_skills, "PIPELINE", skills / "pipeline.yaml")
    assert any("top-level `version`" in p for p in lint_skills.lint())


def test_lint_accepts_metadata_version(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    _write_skill(
        skills,
        'name: sre-foo\ndescription: a test skill description\n'
        'allowed-tools: ["codebase", "search"]\nmetadata:\n  version: 0.1.0',
    )
    monkeypatch.setattr(lint_skills, "SKILLS", skills)
    monkeypatch.setattr(lint_skills, "PIPELINE", skills / "pipeline.yaml")
    assert lint_skills.lint() == []


def test_lint_requires_manifest_when_skills_exist(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    (skills / "sre-foo").mkdir(parents=True)
    (skills / "sre-foo" / "SKILL.md").write_text(
        "---\nname: sre-foo\ndescription: a test skill description\n---\n", encoding="utf-8"
    )
    monkeypatch.setattr(lint_skills, "SKILLS", skills)
    monkeypatch.setattr(lint_skills, "PIPELINE", skills / "pipeline.yaml")  # absent
    assert any("pipeline.yaml" in p for p in lint_skills.lint())
