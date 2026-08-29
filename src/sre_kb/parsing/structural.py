"""Read-only, in-process adapter over :mod:`ast_grep_py`.

Only built-in ast-grep languages are accepted. Scanned repositories cannot register a dynamic
grammar, search the filesystem, edit a node, or launch ast-grep's CLI. The adapter receives one
bounded source string and returns immutable spans and captures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ast_grep_py import SgRoot

EXECUTION_MODEL = "in-process/read-only"

# Keep this explicit. Passing an unsupported language into SgRoot currently raises a native
# PanicException, and accepting target-provided language registrations would cross the trust
# boundary described above.
SUPPORTED_LANGUAGES = frozenset(
    {
        "bash",
        "csharp",
        "go",
        "java",
        "javascript",
        "python",
        "tsx",
        "typescript",
    }
)


class StructuralQueryError(ValueError):
    """The requested trusted structural query cannot be evaluated safely."""


@dataclass(frozen=True)
class StructuralRule:
    rule_id: str
    category: str
    summary: str
    languages: frozenset[str]
    configs: tuple[Mapping[str, object], ...]
    captures: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructuralMatch:
    rule_id: str
    category: str
    summary: str
    language: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    text: str
    captures: dict[str, tuple[str, ...]] = field(default_factory=dict)


def find_structural_matches(
    text: str,
    language: str,
    rules: Sequence[StructuralRule],
    *,
    max_matches: int = 500,
) -> list[StructuralMatch]:
    """Apply trusted ast-grep rules to one source string without any external effects."""
    normalized = language.lower()
    if normalized not in SUPPORTED_LANGUAGES:
        raise StructuralQueryError(
            f"ast-grep language {language!r} is not supported by the in-process allowlist"
        )
    if max_matches < 1:
        return []

    try:
        root = SgRoot(text, normalized).root()
        matches: dict[tuple[str, int, int], StructuralMatch] = {}
        for rule in rules:
            if normalized not in rule.languages:
                continue
            for config in rule.configs:
                for node in root.find_all(**dict(config)):
                    span = node.range()
                    captures: dict[str, tuple[str, ...]] = {}
                    for name in sorted(rule.captures):
                        single = node.get_match(name)
                        values = (
                            (single.text(),)
                            if single is not None
                            else tuple(item.text() for item in node.get_multiple_matches(name))
                        )
                        if values:
                            captures[name] = values
                    match = StructuralMatch(
                        rule_id=rule.rule_id,
                        category=rule.category,
                        summary=rule.summary,
                        language=normalized,
                        start_line=span.start.line + 1,
                        end_line=span.end.line + 1,
                        start_byte=span.start.index,
                        end_byte=span.end.index,
                        text=node.text(),
                        captures=captures,
                    )
                    matches.setdefault((rule.rule_id, match.start_byte, match.end_byte), match)
                    if len(matches) >= max_matches:
                        return _ordered(matches.values())
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        # PyO3 exposes Rust panics outside Exception. Convert them into a controlled boundary error
        # instead of allowing one malformed trusted query to abort a repository scan.
        raise StructuralQueryError(f"ast-grep query failed for {normalized}: {exc}") from exc
    return _ordered(matches.values())


def _ordered(matches) -> list[StructuralMatch]:
    return sorted(
        matches,
        key=lambda item: (item.start_byte, item.end_byte, item.rule_id),
    )


__all__ = [
    "EXECUTION_MODEL",
    "SUPPORTED_LANGUAGES",
    "StructuralMatch",
    "StructuralQueryError",
    "StructuralRule",
    "find_structural_matches",
]
