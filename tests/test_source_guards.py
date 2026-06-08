"""Source-level guardrails: AST checks over src/ that stop a known footgun class from regressing.

These are cheap, deterministic invariants — not style. Each one corresponds to a bug we actually
hit, so the guard keeps the whole tree honest rather than relying on reviewers to spot a repeat.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def _src_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def test_subprocess_run_always_has_a_timeout():
    """A network-bound subprocess.run with no timeout can hang the engine indefinitely in CI (the
    forge clone/push path). Every subprocess.run call must pass timeout=."""
    offenders: list[str] = []
    for path in _src_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and not any(kw.arg == "timeout" for kw in node.keywords)
            ):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, "subprocess.run without timeout=: " + ", ".join(offenders)
