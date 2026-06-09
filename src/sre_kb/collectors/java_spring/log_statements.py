"""Log-statement collector (S2 `assess-logging`, Tier-A): parse the log *statements* in code.

The sibling `observability.py` reads the logback *config* (the format/pattern + MDC fields). This
collector reads the *statements themselves* from the Java AST — the logging API in use, each call's
level, and whether its message is parameterized — so the engine can assess logging quality
deterministically (level discipline + request/trace-ID context) and so a log-based `Alert` keys on a
parsed, byte-grounded format rather than an unparsed one (the S2 prerequisite).

Two fact types, both byte-grounded:
  - ``observability.log.framework`` — the logging API a file uses (slf4j / log4j2 / jul /
    commons-logging), cited to its import line.
  - ``observability.log.statement`` — one per log call: its canonical level and whether the message
    is parameterized (slf4j ``{}`` placeholders vs string concatenation), cited to the call line.

The scaffolder rolls these into the ``Observability`` ``logging`` sub-section (``statements`` +
``quality``); the Tier-B ``sre-assess-logging`` skill handles the judgment calls the engine can't
prove (is this error *noise*?).
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol

# Method name (lower-cased) -> canonical level. slf4j / log4j2 share the five level methods; the JUL
# level methods map onto the same canonical vocabulary so a roll-up is framework-neutral.
_LEVEL_METHODS = {
    "trace": "trace", "debug": "debug", "info": "info", "warn": "warn", "error": "error",
    "warning": "warn", "severe": "error", "config": "debug",
    "fine": "debug", "finer": "trace", "finest": "trace",
}

# Logger-shaped receiver names. A level-named method (`error`) on a non-logger receiver (`metrics`)
# must not count as a log statement, so we also require the receiver to look like a logger — the
# same conservative test `parsing/code_model.py` uses for swallow detection.
_LOG_RECEIVERS = {"log", "logger", "_log", "_logger", "slf4j", "logging"}

# Import prefix -> the logging API it declares (longest-prefix wins, so the lombok rows beat the bare
# package rows). Detection is data, not code, mirroring `inventory_signatures.py`.
_IMPORT_FRAMEWORKS = (
    ("org.slf4j.", "slf4j"),
    ("lombok.extern.slf4j.", "slf4j"),
    ("org.apache.logging.log4j.", "log4j2"),
    ("lombok.extern.log4j.", "log4j2"),
    ("org.apache.commons.logging.", "commons-logging"),
    ("java.util.logging.", "jul"),
)


def _is_log_call(receiver: str, method: str) -> bool:
    # No endswith("log") clause: it would misfire on `catalog`/`backlog`/`dialog` — the exact
    # false positive the code_model receiver test was designed to avoid.
    r, m = receiver.lower(), method.lower()
    return m in _LEVEL_METHODS and (r in _LOG_RECEIVERS or r.endswith("logger"))


def _framework_fact(ctx: ScanContext, rel: str) -> Fact | None:
    """Detect the logging API a file uses from its imports, cited to the matching import line."""
    for lineno, raw in enumerate(ctx.read_lines(rel), start=1):
        line = raw.strip()
        if not line.startswith("import "):
            continue
        imported = line[len("import "):].lstrip("static ").rstrip(";").strip()
        for prefix, framework in _IMPORT_FRAMEWORKS:
            if imported.startswith(prefix):
                return Fact(
                    "observability.log.framework",
                    {"framework": framework, "file": rel},
                    ctx.evidence(rel, lineno, lineno, "java_spring.log_statements"),
                    Symbol(framework, "logging-api"),
                )
    return None


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        fw = _framework_fact(ctx, rel)
        if fw is None:
            continue  # no logging API import -> no log statements to attribute to a framework
        facts.append(fw)
        module = ctx.module(rel, "java")
        for typedecl in module.types:
            for method in typedecl.methods:
                for call in method.calls:
                    if not _is_log_call(call.receiver, call.method):
                        continue
                    message = call.str_args[0] if call.str_args else None
                    facts.append(
                        Fact(
                            "observability.log.statement",
                            {
                                "level": _LEVEL_METHODS[call.method.lower()],
                                "hasMessage": message is not None,
                                # slf4j/log4j2 `{}` placeholder style — a concatenated message
                                # (no `{}`) is the format/quality smell a log alert can't match on.
                                "parameterized": bool(message and "{}" in message),
                                "framework": fw.attrs["framework"],
                            },
                            ctx.evidence(rel, call.line, call.line, "java_spring.log_statements"),
                            Symbol(f"{rel}:{call.line}", "log-statement"),
                        )
                    )
    return facts
