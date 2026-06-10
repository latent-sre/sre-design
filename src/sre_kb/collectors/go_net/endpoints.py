"""Go endpoint + egress collector (AST-backed) — the second Go slice.

Reads the Go AST (`parsing.code_model`, which synthesizes each `router.GET("/path", handler)` route
into the decorator-shaped method the FastAPI/Spring/Express collectors use) and emits the same
normalized facts: `rest.endpoint` per route and `http.egress` per stdlib `net/http` client call in an
inline handler. The unchanged scaffolder turns these into the same `Interface` KB kind.

Scope of this slice: verb-method routes (gin/echo/chi/fiber) with a literal path, and egress via the
`net/http` package-level client funcs (`http.Get/Post/Head/PostForm`). `net/http` `HandleFunc`
routing, custom client types, and cross-function handlers are known recall gaps (parity with the
single-handler limits of the other stacks).

Self-gating: a target with no `*.go` files emits nothing.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import first_url_arg

_HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}
_EGRESS_RECEIVERS = {"http"}            # net/http package-level client funcs
_EGRESS_METHODS = {"get", "post", "head", "postform"}


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    go_files = ctx.files("*.go")
    if not go_files:
        return facts

    for path in go_files:
        rel = ctx.rel(path)
        module = ctx.module(rel, "go")
        for t in module.types:
            for m in t.methods:
                handler = m.name or "anonymous"
                for ann, args in m.annotations.items():
                    verb = ann.rsplit(".", 1)[-1].lower()  # "r.get" -> "get"
                    if verb in _HTTP_VERBS and args.get(""):
                        facts.append(Fact(
                            "rest.endpoint",
                            {"method": verb.upper(), "path": args[""], "handler": handler},
                            ctx.evidence(rel, m.start, m.name_line, "go_net.endpoints"),
                            Symbol(handler, "method"),
                        ))
                for c in m.calls:
                    if c.method.lower() in _EGRESS_METHODS and c.receiver.lower() in _EGRESS_RECEIVERS:
                        attrs = {"class": f"{rel}#{handler}", "client": c.receiver}
                        url = first_url_arg(c.str_args)
                        if url:
                            attrs["url"] = url
                        facts.append(Fact(
                            "http.egress",
                            attrs,
                            ctx.evidence(rel, c.line, c.line, "go_net.endpoints"),
                            Symbol(handler, "method"),
                        ))
    return facts
