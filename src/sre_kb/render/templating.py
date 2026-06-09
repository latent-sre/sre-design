"""Shared rendering primitives for the free-text projections: a sandboxed Jinja2 environment plus the
sanitizing filters that keep untrusted, repo-derived values from breaking out of a Markdown document.

**Where templates apply.** Free-text *prose* projections (the Copilot guardrails and the runbook
Markdown) render through this environment — large static documents with a little structure are far
clearer as a template than as `"\\n".join(lines)`. Structured projections stay in Python on purpose:

  * YAML/JSON outputs (alert ``expr``, dashboard panels, ``catalog-info.yaml``) build native dicts and
    serialize with the YAML/JSON dumper — hand-templating a structured format invites quoting/injection
    bugs that a real serializer cannot make.
  * Mermaid diagrams are a small graph serializer (loops, participant mapping); they read better as the
    Python in ``render/diagrams.py``. They still sanitize through the shared :func:`mermaid` filter so
    escaping lives in exactly one place.

This split mirrors the comparison engine (``resiliency-skills``): it templatizes ``runbook.md.j2`` and
the line-oriented alert adapters, but keeps ``mermaid.py`` as Python.

**Security posture.** Repo-derived values (service/symbol/route names) are untrusted, so the
environment is a :class:`~jinja2.sandbox.SandboxedEnvironment` — it blocks template-level
attribute/attack access even if a hostile value ever reaches a template expression. ``autoescape`` is
OFF because the outputs are Markdown, not HTML; per-value safety is the job of the :func:`inline`
filter (newline/backtick neutralization), not HTML escaping. :class:`~jinja2.StrictUndefined` makes a
missing context key fail loud at render time instead of emitting a silent blank.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from jinja2 import FileSystemLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

TEMPLATES_DIR = Path(__file__).parent / "templates"

_WS = re.compile(r"\s+")
# Mermaid metacharacters that could break out of a label/message or inject diagram syntax.
_MERMAID_META = re.compile(r'[;:|<>"#%(){}\[\]`\\]')


def inline(text: object) -> str:
    """Flatten a value to one safe line before it lands in a Markdown guardrail/runbook: collapse
    whitespace (kills newline-injected bullets/instructions) and drop backticks (kills code-span
    breakout). Guardrails are rules the developer is told to obey, so an injected line must never
    masquerade as one."""
    return _WS.sub(" ", str(text)).replace("`", "").strip()


def mermaid(text: object) -> str:
    """Sanitize a value for a Mermaid label/message: collapse whitespace, then strip the
    metacharacters that could break out of a label or inject diagram syntax (render-integrity, not
    RCE). Mirrors the node-id sanitization applied in ``render/diagrams``."""
    return _MERMAID_META.sub("", _WS.sub(" ", str(text))).strip()


@cache
def env() -> SandboxedEnvironment:
    """The process-wide sandboxed Jinja2 environment for free-text projections. Cached: the loader
    and filters are stateless, so one environment serves every render."""
    e = SandboxedEnvironment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    e.filters["inline"] = inline
    e.filters["mermaid"] = mermaid
    # Markdown hard line-break (two trailing spaces) as an explicit global, so the semantic trailing
    # whitespace in a template survives editors/formatters that would otherwise strip it.
    e.globals["HB"] = "  "
    return e


def render(template: str, **context: object) -> str:
    """Render the named template from the shared environment with ``context``."""
    return env().get_template(template).render(**context)
