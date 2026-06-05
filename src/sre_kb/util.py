"""Small shared helpers for collectors (text/line lookups, durations, Java symbols)."""

from __future__ import annotations

import re
from typing import Any

_PKG = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
_TYPE = re.compile(r"\b(?:class|interface|enum)\s+([A-Z]\w*)")
_DURATION = re.compile(r"^\s*(\d+)\s*(ms|s|m)\s*$")


def find_line(lines: list[str], needle: str, start: int = 0) -> int | None:
    """1-based line number of the first line (at/after 0-based `start`) containing needle."""
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i + 1
    return None


def dig(data: Any, *keys: str) -> Any:
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def parse_duration_ms(value: str | None) -> int | None:
    if value is None:
        return None
    m = _DURATION.match(str(value))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"ms": n, "s": n * 1000, "m": n * 60_000}[unit]


def java_package(text: str) -> str:
    m = _PKG.search(text)
    return m.group(1) if m else ""


def java_type(text: str) -> str:
    m = _TYPE.search(text)
    return m.group(1) if m else "Unknown"


def fqn(pkg: str, type_name: str, member: str | None = None) -> str:
    base = f"{pkg}.{type_name}" if pkg else type_name
    return f"{base}#{member}" if member else base


def slug(text: str) -> str:
    """Make a value safe for metadata.name (^[a-z0-9][a-z0-9-]*$). Splits camelCase."""
    text = re.sub(r"(?<!^)(?=[A-Z])", "-", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or "x"


def member_of(symbol_fqn: str) -> str:
    """Return the member portion of 'pkg.Type#member', else the type name."""
    return symbol_fqn.split("#")[-1] if symbol_fqn else "x"
