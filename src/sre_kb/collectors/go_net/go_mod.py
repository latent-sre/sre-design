"""Go `go.mod` collector — emits the normalized tech-stack facts the unchanged scaffolder turns into
a `TechStack`, same as the Java/.NET/Python/Node collectors. Direct parse only; safe-by-default
(no build executed, no AST, no new dependency).

Scope of this slice: web framework (gin/echo/chi/fiber/mux/...), runtime (go + gomod), and the
direct module dependency list. `// indirect` (transitive) requires are skipped — they are not the
service's declared posture, the same reason the Node slice skips devDependencies. HTTP route and
egress extraction need a Go AST and are a follow-up.

Self-gating: a target with no `go.mod` emits nothing.
"""

from __future__ import annotations

import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line

# Module-path substring -> canonical framework label. Ordered most-specific first; first match wins.
_FRAMEWORKS: tuple[tuple[str, str], ...] = (
    ("gin-gonic/gin", "gin"),
    ("labstack/echo", "echo"),
    ("gofiber/fiber", "fiber"),
    ("go-chi/chi", "chi"),
    ("gorilla/mux", "gorilla-mux"),
    ("beego/beego", "beego"),
    ("gobuffalo/buffalo", "buffalo"),
)

# A require line inside a block (or after `require `): `<module-path> v<version>`, optionally
# trailing ` // indirect`. The module path is everything up to the first whitespace.
_REQUIRE = re.compile(r"^(?P<mod>[^\s]+)\s+(?P<version>v\S+)(?P<tail>.*)$")


def _direct_requires(lines: list[str]) -> list[tuple[str, str, int]]:
    """(module path, version, 1-based line) for each *direct* require in a go.mod — block or
    single-line form, skipping `// indirect` transitive deps."""
    out: list[tuple[str, str, int]] = []
    in_block = False
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if in_block:
            if line.startswith(")"):
                in_block = False
                continue
            body = line
        elif line.startswith("require ("):
            in_block = True
            continue
        elif line.startswith("require "):
            body = line.removeprefix("require ").strip()
        else:
            continue
        m = _REQUIRE.match(body)
        if m and "// indirect" not in m.group("tail"):
            out.append((m.group("mod"), m.group("version"), i))
    return out


def _framework(modules: set[str]) -> tuple[str, str] | None:
    """The (module path, canonical label) of the web framework among the modules, or None."""
    return next(
        ((mod, label) for hint, label in _FRAMEWORKS for mod in modules if hint in mod),
        None,
    )


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    mods = ctx.files("go.mod")
    if not mods:
        return facts

    seen: set[str] = set()
    runtime_done = False
    for path in mods:
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        requires = _direct_requires(lines)
        modules = {m for m, _, _ in requires}

        if not runtime_done:
            ln = find_line(lines, "module ") or 1
            ev = ctx.evidence(rel, ln, ln, "go_net.go_mod")
            facts.append(Fact(
                "tech.runtime",
                {"language": "go", "runtime": "go", "buildTool": "gomod"},
                ev, Symbol("go", "runtime"),
            ))
            fw = _framework(modules)
            if fw:
                mod_path, label = fw
                fln = find_line(lines, mod_path) or ln
                facts.append(Fact(
                    "tech.framework", {"name": label},
                    ctx.evidence(rel, fln, fln, "go_net.go_mod"),
                    Symbol(label, "framework"),
                ))
            runtime_done = True

        for mod, version, ln in requires:
            if mod in seen:
                continue
            seen.add(mod)
            facts.append(Fact(
                "tech.dependency", {"name": mod, "version": version},
                ctx.evidence(rel, ln, ln, "go_net.go_mod"),
                Symbol(mod, "dependency"),
            ))
    return facts
