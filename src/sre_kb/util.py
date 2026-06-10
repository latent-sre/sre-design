"""Small shared helpers for collectors (text/line lookups, durations, Java symbols)."""

from __future__ import annotations

import re
from typing import Any

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


def dig_ci(data: Any, *keys: str) -> Any:
    """`dig` with case-insensitive key matching (.NET configuration semantics)."""
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = next((v for k, v in cur.items()
                    if isinstance(k, str) and k.lower() == key.lower()), None)
    return cur


def url_host(value: Any) -> str:
    """The bare hostname of a route/baseUrl/URL: scheme, path, and port stripped, lowercased.
    Every consumer of a hostname join (the estate route<->baseUrl resolution, frontend client
    naming) MUST normalize through this one function — an asymmetry silently breaks the join."""
    rest = str(value or "").split("://", 1)[-1]
    return rest.split("/", 1)[0].rsplit(":", 1)[0].strip().lower()


def artifact_filename(name: object) -> str:
    """Filesystem-safe `<name>.yaml` for an artifact write. A valid metadata.name
    (^[a-z0-9][a-z0-9-]*$) passes through unchanged (slug is the identity on it); anything
    else — notably a REJECTED doc whose very rejection may be a hostile name carrying path
    separators — is slugged so the write can never escape its directory."""
    return f"{slug(str(name))}.yaml"


def first_url_arg(args: tuple[str, ...]) -> str | None:
    """The first string-literal call argument that looks like a URL or path — the
    consumer-side contract anchor every stack's http.egress collector captures identically."""
    return next((a for a in args if a.startswith(("http://", "https://", "/"))), None)


def parse_duration_ms(value: str | None) -> int | None:
    if value is None:
        return None
    m = _DURATION.match(str(value))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"ms": n, "s": n * 1000, "m": n * 60_000}[unit]


def fqn(pkg: str, type_name: str, member: str | None = None) -> str:
    base = f"{pkg}.{type_name}" if pkg else type_name
    return f"{base}#{member}" if member else base


def slug(text: str) -> str:
    """Make a value safe for metadata.name (^[a-z0-9][a-z0-9-]*$). Splits camelCase."""
    text = re.sub(r"(?<!^)(?=[A-Z])", "-", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or "x"


def member_of(symbol_fqn: str) -> str:
    """Return the member portion of 'pkg.Type#member', else the whole symbol unchanged."""
    return symbol_fqn.split("#")[-1] if symbol_fqn else "x"


def swallow_level(log_method: str) -> str:
    """Normalize a catch/except log call to a bare level so the swallowed.failure `level` is
    consistent across stacks: strip a leading `log` (C# `LogError` -> error) and lowercase
    (slf4j `error` -> error). Without this, the same fact kind carried `LogError` vs `error`."""
    core = log_method[3:] if log_method[:3].lower() == "log" else log_method
    return core.lower()
