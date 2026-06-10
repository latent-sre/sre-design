"""Frontend (SPA) collector — what a frontend repo already declares about its backend:
CRA's package.json `proxy`, vite/webpack devServer proxy targets, `.env` `*_API_URL`
variables, and axios `baseURL` constants. Each becomes a `config.client`-equivalent fact
(client + baseUrl), so a SPA flows through the estate route<->baseUrl join unchanged and
connects to its API repo with zero manual declaration (NEXT-INCREMENTS §5.4).

Also emits a `tech.frontend` fact when a frontend framework is among the dependencies, so
the SPA's own topology node renders as `frontend` rather than a generic service.

Self-gating: no package.json -> emits nothing.
"""

from __future__ import annotations

import json
import re

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, Symbol
from sre_kb.util import find_line, slug, url_host

_DETECTOR = "node_express.frontend"

# Dependency name -> canonical frontend framework label, most-specific first (a Next app
# also depends on react; first match wins).
_FRONTEND_FRAMEWORKS: tuple[tuple[str, str], ...] = (
    ("next", "nextjs"),
    ("nuxt", "nuxt"),
    ("@angular/core", "angular"),
    ("svelte", "svelte"),
    ("vue", "vue"),
    ("preact", "preact"),
    ("react", "react"),
)

# KEY=VALUE lines whose key declares an API base URL (VITE_ORDERS_API_URL=, REACT_APP_...).
_ENV_API_URL = re.compile(r"^\s*([A-Z][A-Z0-9_]*_API_URL)\s*=\s*(\S+)\s*$")
_ENV_PREFIXES = ("VITE_", "REACT_APP_", "NEXT_PUBLIC_", "VUE_APP_")

# devServer/proxy entries in vite/webpack config: `'/api': { target: 'http://orders' }`
# and the short string form `'/api': 'http://orders'`.
_PROXY_TARGET = re.compile(
    r"""['"](/[^'"]*)['"]\s*:\s*(?:\{[^{}]*?target\s*:\s*['"]([^'"]+)['"]|['"](https?://[^'"]+)['"])""",
    re.S,
)

_AXIOS_BASEURL = re.compile(r"""baseURL\s*[:=]\s*['"]([^'"]+)['"]""")


def _client_name(url: str, fallback: str) -> str:
    """A stable client name for a declared backend URL: the hostname's first label when the
    URL carries one, else the caller's fallback (env-var stem, proxy route)."""
    # util.url_host is the estate join's normalizer — the two sides must not diverge.
    label = url_host(url).split(".", 1)[0]
    return slug(label) if label and not label.replace(".", "").isdigit() else slug(fallback)


def collect(ctx: ScanContext) -> list[Fact]:
    facts: list[Fact] = []
    pkgs = ctx.files("package.json")
    if not pkgs:
        return facts
    seen: set[tuple[str, str]] = set()

    def add_client(client: str, base_url: str, rel: str, ln: int) -> None:
        if not base_url or (client, base_url) in seen:
            return
        seen.add((client, base_url))
        facts.append(Fact(
            "config.client",
            {"client": client, "baseUrl": base_url, "source": "frontend"},
            ctx.evidence(rel, ln, ln, _DETECTOR),
            Symbol(client, "client"),
        ))

    frontend_done = False
    for path in pkgs:
        rel = ctx.rel(path)
        lines = ctx.read_lines(rel)
        try:
            data = json.loads(ctx.read_text(rel)) or {}
        except (json.JSONDecodeError, ValueError):
            continue  # package_json.collect already records the parse error
        if not isinstance(data, dict):
            continue
        deps = data.get("dependencies") or {}
        if not frontend_done and isinstance(deps, dict):
            hit = next(((d, label) for d, label in _FRONTEND_FRAMEWORKS if d in deps), None)
            if hit:
                dep, label = hit
                ln = find_line(lines, f'"{dep}"') or 1
                facts.append(Fact(
                    "tech.frontend", {"framework": label},
                    ctx.evidence(rel, ln, ln, _DETECTOR),
                    Symbol(label, "frontend"),
                ))
                frontend_done = True
        proxy = data.get("proxy")
        if isinstance(proxy, str):
            ln = find_line(lines, '"proxy"') or 1
            add_client(_client_name(proxy, "proxy"), proxy, rel, ln)

    for path in ctx.files(".env", ".env.*"):
        rel = ctx.rel(path)
        for i, line in enumerate(ctx.read_lines(rel), 1):
            m = _ENV_API_URL.match(line)
            if not m:
                continue
            key, url = m.group(1), m.group(2).strip("'\"")
            stem = key
            for prefix in _ENV_PREFIXES:
                stem = stem.removeprefix(prefix)
            stem = stem.removesuffix("_API_URL") or "api"
            add_client(_client_name(url, stem), url, rel, i)

    for path in ctx.files("vite.config.*", "webpack.config.*", "webpack.*.config.*"):
        rel = ctx.rel(path)
        text = ctx.read_text(rel)
        lines = ctx.read_lines(rel)
        for m in _PROXY_TARGET.finditer(text):
            route, target = m.group(1), m.group(2) or m.group(3)
            ln = text.count("\n", 0, m.start()) + 1
            add_client(_client_name(target, route.strip("/") or "proxy"), target, rel, ln)

    if frontend_done:  # axios constants only make sense in a frontend codebase
        for path in ctx.files("*.js", "*.jsx", "*.ts", "*.tsx"):
            rel = ctx.rel(path)
            text = ctx.read_text(rel)
            if "baseURL" not in text:
                continue  # skip the regex over ~all files in a large frontend repo
            for m in _AXIOS_BASEURL.finditer(text):
                url = m.group(1)
                if not url.startswith(("http://", "https://")):
                    continue  # relative baseURLs carry no cross-repo signal
                ln = text.count("\n", 0, m.start()) + 1
                add_client(_client_name(url, "api"), url, rel, ln)
    return facts
