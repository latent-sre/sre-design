"""Plain-English projections for non-developer responders.

Deterministic re-statements of already-validated artifact fields, from a fixed engine
vocabulary — the same trust class as the topology legend and the Copilot guardrails: every
sentence is a projection of fields the KB already carries (step kinds, failure modes,
surfaced effects), never an inference beyond them. Unknown tokens fall back to the raw
value, sanitized through the shared `inline` filter.

`evidence_excerpt` additionally lets a projection embed the exact cited bytes: it re-reads
`path:lines` under the target root and embeds ONLY when the bytes still hash to the
artifact's `excerptHash` — a drifted file embeds nothing rather than code the artifact never
cited. Embedded excerpts are staged output like any other, so the publish-time secret-scan
gate covers them.
"""

from __future__ import annotations

import re
from pathlib import Path

from sre_kb.render.templating import inline as _inline

# --- fixed vocabulary -------------------------------------------------------------------------

# Step kinds -> what the service is doing, for someone who has never read the code.
_STEP_PHRASE = {
    "http-egress": "calls another service",
    "db-write": "writes to the database",
    "db-read": "reads from the database",
    "message-egress": "publishes an event to the message broker",
}

# Failure modes -> what went wrong, in plain words.
_MODE_PHRASE = {
    "timeout": "the call takes too long (timeout)",
    "circuit-open": "the circuit breaker is open after repeated failures",
    "db-unavailable": "the database is unreachable",
    "broker-unavailable": "the message broker is unreachable",
}

# surfacedAs -> what the outside world sees when that failure happens.
_SURFACED_PHRASE = {
    "http-503": "callers get HTTP 503 (service temporarily unavailable)",
    "http-500": "callers get HTTP 500 (server error)",
    "logged-and-swallowed": "the error is only written to the log and then ignored",
}

_DATA_LOSS_PHRASE = "THE DATA IS LOST — there is no built-in replay"


def step_phrase(kind: str | None) -> str:
    return _STEP_PHRASE.get(str(kind), f"runs step kind {_inline(kind)}")


def mode_phrase(mode: str | None) -> str:
    return _MODE_PHRASE.get(str(mode), _inline(mode))


def surfaced_phrase(surfaced: str | None) -> str:
    return _SURFACED_PHRASE.get(str(surfaced), f"surfaced as {_inline(surfaced)}")


def failure_sentence(fm: dict) -> str:
    """One failure mode -> 'If <what went wrong>, <what callers see>[ and <data loss>].'"""
    out = f"If {mode_phrase(fm.get('mode'))}, {surfaced_phrase(fm.get('surfacedAs'))}"
    if fm.get("dataLossRisk"):
        out += f" and {_DATA_LOSS_PHRASE}"
    return out + "."


def flow_plain_english(flow: dict) -> list[str]:
    """Numbered plain-English narration of a Flow artifact: the trigger, then one line per
    step naming what the service does, the target (when steps/sinks pair — the same
    index-parallel guard the diagram renderer uses), and each failure mode's plain sentence."""
    spec = flow.get("spec", {})
    trigger = spec.get("trigger", {})
    service = (flow.get("metadata") or {}).get("service", "the service")
    steps = spec.get("steps", [])
    sinks = spec.get("sinks", [])
    paired = sinks if len(sinks) == len(steps) else [None] * len(steps)

    req = f"{_inline(trigger.get('method', ''))} {_inline(trigger.get('path', ''))}".strip()
    lines = [f"1. A client sends `{req}` to {_inline(service)}." if req
             else f"1. A trigger starts this flow in {_inline(service)}."]
    for i, (step, sink) in enumerate(zip(steps, paired), start=2):
        doing = step_phrase(step.get("kind"))
        target = (sink or {}).get("target") if isinstance(sink, dict) else None
        where = f" (`{_inline(target)}`)" if target else ""
        line = f"{i}. The service {doing}{where} — step `{_inline(step.get('name', 'step'))}`."
        for fm in step.get("failureModes", []):
            line += f" {failure_sentence(fm)}"
        lines.append(line)
    return lines


# --- verbatim evidence excerpts ---------------------------------------------------------------

_MAX_EXCERPT_LINES = 40  # an oversized citation is skipped, never truncated (verbatim or nothing)

_LANG_BY_SUFFIX = {
    ".java": "java", ".cs": "csharp", ".py": "python", ".js": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".go": "go",
    ".yaml": "yaml", ".yml": "yaml", ".xml": "xml", ".properties": "properties",
}


def _within(root: Path, p: Path) -> bool:
    try:
        return p.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def evidence_excerpt(ev: dict, target_root: Path) -> dict | None:
    """The verbatim cited bytes for one evidence item, or None when they can't be embedded
    honestly: path escapes the root, the range is out of bounds or oversized, or the bytes
    no longer hash to the artifact's `excerptHash` (the file drifted since the scan).

    Returns {"header": "path:start-end", "lang": <fence language>, "fence": <backtick run>,
    "code": <exact lines>}; the fence is always longer than any backtick run inside the code,
    so the excerpt cannot break out of its block.
    """
    from sre_kb.collectors.base import hash_excerpt

    path = ev.get("path")
    lines = ev.get("lines") or {}
    start, end = lines.get("start"), lines.get("end")
    if not path or not (isinstance(start, int) and isinstance(end, int)):
        return None
    if start < 1 or start > end or end - start + 1 > _MAX_EXCERPT_LINES:
        return None
    fpath = target_root / path
    if not _within(target_root, fpath) or not fpath.exists():
        return None
    content = fpath.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if end > len(content):
        return None
    if hash_excerpt(content, start, end) != ev.get("excerptHash"):
        return None  # the file changed since the scan — embedding it would mis-cite
    code = "".join(content[start - 1 : end]).rstrip("\n")
    longest_run = max((len(m.group(0)) for m in re.finditer(r"`+", code)), default=0)
    return {
        "header": f"{path}:{start}-{end}",
        "lang": _LANG_BY_SUFFIX.get(Path(path).suffix, ""),
        "fence": "`" * max(3, longest_run + 1),
        "code": code,
    }


def runbook_excerpts(runbook: dict, target_root: Path | None) -> list[dict]:
    """The embeddable excerpts for a runbook's evidence list, de-duplicated by citation."""
    if target_root is None:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for ev in runbook.get("evidence") or []:
        x = evidence_excerpt(ev, target_root)
        if x and x["header"] not in seen:
            seen.add(x["header"])
            out.append(x)
    return out
