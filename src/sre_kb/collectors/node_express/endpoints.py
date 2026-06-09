"""Node.js / Express endpoint + egress collector (AST-backed) — the second Node slice.

Reads the JavaScript AST (`parsing.code_model`, which synthesizes each Express route into the
decorator-shaped method the FastAPI/Spring collectors use) and emits the same normalized facts:
`rest.endpoint` per `app.<verb>('/path', handler)` and `http.egress` per outbound HTTP client call
in a handler body. The unchanged scaffolder turns these into the same `Interface` KB kind.

Scope of this slice: routes registered as `app`/`router` method calls with a literal path, and egress
via axios/got/superagent/ky/`fetch`. Template-literal paths, chained `app.route('/x').get(...)`, and
cross-file handlers are known recall gaps (parity with the single-handler limits of the other stacks).

Self-gating: a target with no `*.js`/`*.mjs`/`*.cjs` files emits nothing.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol

_JS_GLOBS = ("*.js", "*.mjs", "*.cjs")
_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "options", "head"}
# Outbound HTTP clients whose `<receiver>.<verb>(...)` is a dependency call. Only unambiguous HTTP
# client modules — a bare `fetch(...)` is handled separately (no receiver).
_EGRESS_RECEIVERS = {"axios", "got", "superagent", "ky"}
_EGRESS_METHODS = _HTTP_VERBS | {"request"}


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    js_files = ctx.files(*_JS_GLOBS)
    if not js_files:
        return facts

    for path in js_files:
        rel = ctx.rel(path)
        module = ctx.module(rel, "javascript")
        for t in module.types:
            for m in t.methods:
                handler = m.name or "anonymous"
                for ann, args in m.annotations.items():
                    verb = ann.rsplit(".", 1)[-1].lower()  # "app.get" / "router.get" -> "get"
                    if verb in _HTTP_VERBS and args.get(""):
                        facts.append(Fact(
                            "rest.endpoint",
                            {"method": verb.upper(), "path": args[""], "handler": handler},
                            ctx.evidence(rel, m.start, m.name_line, "node_express.endpoints"),
                            Symbol(handler, "method"),
                        ))
                for c in m.calls:
                    meth, recv = c.method.lower(), c.receiver.lower()
                    is_client = meth in _EGRESS_METHODS and recv in _EGRESS_RECEIVERS
                    is_fetch = not c.receiver and meth == "fetch"
                    if is_client or is_fetch:
                        facts.append(Fact(
                            "http.egress",
                            {"class": f"{rel}#{handler}", "client": c.receiver or "fetch"},
                            ctx.evidence(rel, c.line, c.line, "node_express.endpoints"),
                            Symbol(handler, "method"),
                        ))
    return facts
