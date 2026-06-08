"""Structural checks on the shipped Copilot projection assets (skills + agents).

These are the LLM-half's contract: if a SKILL.md links a reference that doesn't exist, the
skill silently half-works in VS Code. Tree-walk every skill/agent and fail loudly on a
broken frontmatter, an over-long body, or a dangling relative link — the same "keep code
and KB in sync" rule the engine holds itself to."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1] / ".github"
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
AGENTS = sorted((ROOT / "agents").glob("*.agent.md"))

_FM = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
_LINK = re.compile(r"\]\(([^)]+)\)")


def _split(path: Path) -> tuple[dict, str]:
    m = _FM.match(path.read_text(encoding="utf-8"))
    assert m, f"{path} missing YAML frontmatter"
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def test_skills_and_agents_exist():
    assert SKILLS, "no skills found"
    names = {_split(s)[0].get("name") for s in SKILLS}
    # the four authoring skills + the consumer skill must all be present
    assert {
        "sre-flow-analysis",
        "sre-prr-review",
        "sre-blast-radius",
        "sre-estate",
        "sre-incident-response",
    } <= names


_MUTATING_TOOLS = {"editFiles", "runCommands"}


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_and_body(skill: Path):
    fm, body = _split(skill)
    assert fm.get("name"), f"{skill} needs a name"
    assert fm.get("description"), f"{skill} needs a description"
    assert fm["name"] == skill.parent.name, f"{skill}: name must match folder"
    # GA requirement: SKILL.md body stays under 500 lines (progressive disclosure).
    assert len(body.splitlines()) < 500, f"{skill} body too long"
    if "allowed-tools" in fm:  # optional, but if present it must be a list of tool names
        assert isinstance(fm["allowed-tools"], list) and all(isinstance(t, str) for t in fm["allowed-tools"])


def test_consumer_skill_is_read_only():
    """The on-call consumer skill reads a published KB during an incident — it must not be
    able to edit the KB or run mutating commands. Lock that as an invariant, not a comment."""
    fm, _ = _split(ROOT / "skills" / "sre-incident-response" / "SKILL.md")
    tools = set(fm.get("allowed-tools", []))
    assert tools, "consumer skill must pin allowed-tools (read-only)"
    assert not (tools & _MUTATING_TOOLS), f"consumer skill must stay read-only, got {sorted(tools)}"


@pytest.mark.parametrize("agent", AGENTS, ids=lambda p: p.name)
def test_agent_frontmatter(agent: Path):
    fm, _ = _split(agent)
    assert fm.get("name") and fm.get("description"), f"{agent} needs name + description"


@pytest.mark.parametrize("doc", SKILLS + AGENTS, ids=lambda p: p.parent.name + "/" + p.name)
def test_relative_links_resolve(doc: Path):
    for target in _LINK.findall(doc.read_text(encoding="utf-8")):
        if target.startswith(("http://", "https://", "#")):
            continue
        rel = target.split("#", 1)[0]
        assert (doc.parent / rel).exists(), f"{doc}: dangling link -> {target}"


# Skills must be self-contained folders, so shared references (the non-negotiable provenance
# rules, the challenge protocol) are copied into each skill rather than linked across folders.
# That portability has a cost: the copies can drift. Pin them byte-identical so a one-sided
# edit fails CI instead of silently diverging the rules between skills.
@pytest.mark.parametrize("shared", ["provenance-rules.md", "challenge-protocol.md"])
def test_shared_references_stay_identical(shared: str):
    copies = sorted((ROOT / "skills").glob(f"*/references/{shared}"))
    assert len(copies) >= 2, f"expected {shared} bundled into multiple skills"
    bodies = {c.read_text(encoding="utf-8") for c in copies}
    assert len(bodies) == 1, f"{shared} has drifted across skills: {[str(c) for c in copies]}"
