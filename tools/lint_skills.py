#!/usr/bin/env python3
"""Lint .github/skills/*/SKILL.md frontmatter and keep it in sync with the pipeline.

Rules (small on purpose — the schemas/engine do the heavy lifting):
  * every skill dir has a SKILL.md with a YAML frontmatter block,
  * `name` is present and equals the directory name,
  * `description` is present and 10..1024 chars,
  * `allowed-tools` is present and is an inline list of known tool names. The skills
    process untrusted target repos, so every skill declares its tool surface explicitly
    (least privilege). This is a house rule stricter than the GitHub spec (where
    `allowed-tools` is optional); it keeps the read-only consumer skills and the
    command-capable authoring skills from drifting into an undeclared tool surface.
  * a `version`, if present, lives under `metadata` (`metadata: {version: ...}`), never
    as a top-level key, matching docs/DESIGN.md and the GitHub Agent Skills shape,
  * every skill appears exactly once in skills/pipeline.yaml, and vice versa.

stdlib only; exits non-zero on any problem so CI/tests block.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = ROOT / ".github" / "skills"
PIPELINE = SKILLS / "pipeline.yaml"
_RESERVED = {"_shared"}

# VS Code / Copilot built-in tool names the skills may request. Tight on purpose: an
# allowlist catches typos (`runCommand` vs `runCommands`) and forces a conscious edit here
# when a skill genuinely needs a new capability.
_KNOWN_TOOLS = {"codebase", "search", "editFiles", "runCommands"}


def _frontmatter(text: str) -> dict[str, str]:
    """Minimal YAML frontmatter reader (handles `>`/`>-`/`|` block scalars for descriptions)."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    lines = text[3:end].splitlines()
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.strip().startswith("#") or line[:1].isspace() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val and val[0] in "|>":
            fold = val[0] == ">"
            block: list[str] = []
            while i < len(lines) and (lines[i][:1].isspace() or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            out[key] = (" ".join(block) if fold else "\n".join(block)).strip()
        else:
            out[key] = val.strip("'\"")
    return out


def _pipeline_skills() -> set[str]:
    if not PIPELINE.is_file():
        return set()
    out: set[str] = set()
    for line in PIPELINE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("- ") and "name:" not in s and "phase" not in s:
            out.add(s[2:].strip())
    return out


def _lint_tools(name: str, raw: str | None) -> list[str]:
    """Validate a skill's `allowed-tools` declaration (required, inline list, known names)."""
    if raw is None:
        return [f"{name}: missing `allowed-tools` -- declare the tool surface explicitly, "
                f"e.g. allowed-tools: [\"codebase\", \"search\"]"]
    try:
        tools = json.loads(raw)
    except json.JSONDecodeError:
        return [f"{name}: allowed-tools must be an inline list, e.g. [\"codebase\", \"search\"]"]
    if not isinstance(tools, list) or not tools:
        return [f"{name}: allowed-tools must be a non-empty inline list"]
    unknown = [t for t in tools if t not in _KNOWN_TOOLS]
    if unknown:
        return [f"{name}: unknown tool(s) {sorted(unknown)} in allowed-tools "
                f"(known: {sorted(_KNOWN_TOOLS)})"]
    return []


def lint() -> list[str]:
    problems: list[str] = []
    if not SKILLS.is_dir():
        return problems
    skill_dirs = [d for d in SKILLS.iterdir() if d.is_dir() and d.name not in _RESERVED]
    names = set()
    for d in sorted(skill_dirs):
        md = d / "SKILL.md"
        if not md.is_file():
            problems.append(f"{d.name}: missing SKILL.md")
            continue
        fm = _frontmatter(md.read_text(encoding="utf-8"))
        names.add(d.name)
        if fm.get("name") != d.name:
            problems.append(f"{d.name}: frontmatter name={fm.get('name')!r} must equal dir name")
        desc = fm.get("description", "")
        if not (10 <= len(desc) <= 1024):
            problems.append(f"{d.name}: description must be 10..1024 chars (got {len(desc)})")
        if "version" in fm:
            problems.append(
                f"{d.name}: top-level `version` is not allowed -- nest it under `metadata` "
                "(`metadata:` then `  version: ...`)"
            )
        problems.extend(_lint_tools(d.name, fm.get("allowed-tools")))
    pipeline = _pipeline_skills()
    if not PIPELINE.is_file():
        if names:  # the manifest is canonical and required once any skill exists
            problems.append("skills/pipeline.yaml is missing — the canonical skill manifest is required")
    else:
        for missing in sorted(names - pipeline):
            problems.append(f"{missing}: in skills/ but not in pipeline.yaml")
        for extra in sorted(pipeline - names):
            problems.append(f"{extra}: in pipeline.yaml but no skill dir")
    return problems


def main() -> int:
    problems = lint()
    if problems:
        print(f"lint-skills: {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print("lint-skills: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
