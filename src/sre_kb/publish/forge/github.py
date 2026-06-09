"""GitHub forge: git (clone -> branch -> sync tree -> commit -> push) + the REST API to
open the PR. Token comes from GITHUB_TOKEN/GH_TOKEN. The engine does NOT use this
session's MCP tools (those aren't available to a standalone engine in CI).

The git runner and the REST POST are injectable seams so the whole flow is unit-tested
without a token or network; the defaults shell out to `git` and urllib.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Callable

from sre_kb.publish.forge.base import ForgePublishError
from sre_kb.publish.manifest import merge_tree

_GIT_USER = ["-c", "user.email=sre-kb@users.noreply.github.com", "-c", "user.name=sre-kb"]
_GIT_TIMEOUT_S = 300  # bound each git subprocess so a stalled clone/push can't hang the engine in CI


def parse_repo(spec: str) -> tuple[str, str]:
    """Accept owner/name, https://github.com/owner/name(.git), or git@github.com:owner/name.git."""
    s = spec.strip().removesuffix(".git")
    if s.startswith("git@"):
        s = s.split(":", 1)[1] if ":" in s else s
    elif "github.com/" in s:
        s = s.split("github.com/", 1)[1]
    parts = s.strip("/").split("/")
    if len(parts) < 2 or not parts[-1] or not parts[-2]:
        raise ForgePublishError(f"cannot parse owner/repo from {spec!r}")
    return parts[-2], parts[-1]


def _redact(cmd: list[str]) -> list[str]:
    out = []
    for c in cmd:
        c = re.sub(r"x-access-token:[^@]+@", "x-access-token:***@", c)
        c = re.sub(r"(?i)(authorization: (?:basic|bearer) )\S+", r"\1***", c)
        out.append(c)
    return out


@contextmanager
def _git_auth_env(token: str):
    """Provide git HTTPS auth via env-injected config (GIT_CONFIG_*), so the token is never
    on the `git` command line where `ps` could read it. git >= 2.31 reads these keys."""
    header = "Authorization: Basic " + base64.b64encode(f"x-access-token:{token}".encode()).decode()
    keys = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": header,
    }
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update(keys)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _default_run(cmd: list[str]) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=_GIT_TIMEOUT_S)  # noqa: S603
    except subprocess.TimeoutExpired:
        raise ForgePublishError(
            f"git timed out after {_GIT_TIMEOUT_S}s: {' '.join(_redact(cmd))}"
        ) from None
    if res.returncode != 0:
        stderr = _redact([res.stderr.strip()])[0]  # git may echo the tokenized remote URL
        raise ForgePublishError(f"git failed ({res.returncode}): {' '.join(_redact(cmd))}\n{stderr}")
    return res.stdout


def _default_post(url: str, payload: dict, token: str) -> dict:
    req = urllib.request.Request(  # noqa: S310
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "sre-kb",
        },
    )
    # `urlopen` raises HTTPError on any non-2xx (422 PR exists, 401 bad token, 403 rate-limit). Wrap
    # it as ForgePublishError per the Forge contract, and `from None` so the token-bearing request in
    # the original exception's context isn't surfaced in tracebacks/logs.
    try:
        with urllib.request.urlopen(req) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as exc:
        raise ForgePublishError(f"GitHub API {exc.code} opening PR: {exc.reason}") from None
    except urllib.error.URLError as exc:
        raise ForgePublishError(f"GitHub API request failed: {exc.reason}") from None


class GitHubForge:
    name = "github"

    def __init__(
        self,
        *,
        runner: Callable[[list[str]], str] | None = None,
        http_post: Callable[[str, dict, str], dict] | None = None,
        token: str | None = None,
        allowed_repos: list[str] | None = None,
    ):
        self._run = runner or _default_run
        self._post = http_post or _default_post
        self._token = token
        # None = unrestricted (back-compat); a list confines live publishes to those repos.
        self._allowed = None if allowed_repos is None else {"/".join(parse_repo(r)).lower() for r in allowed_repos}

    def open_pr(self, tree: Path, *, sre_repo: str, branch: str, title: str, body: str) -> str:
        token = self._token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise ForgePublishError("set GITHUB_TOKEN to publish live (or use --dry-run)")
        owner, repo = parse_repo(sre_repo)
        if self._allowed is not None and f"{owner}/{repo}".lower() not in self._allowed:
            raise ForgePublishError(
                f"refusing to publish to {owner}/{repo}: not in the publish allowlist "
                f"(publish.allowed_repos)"
            )
        # Tokenless remote; auth is injected via env config (see _git_auth_env) so the token
        # never appears in the git argv that `ps` can read.
        remote = f"https://github.com/{owner}/{repo}.git"
        with tempfile.TemporaryDirectory() as tmp, _git_auth_env(token):
            work = Path(tmp) / "repo"
            self._run(["git", "clone", "--depth", "1", remote, str(work)])
            base = (self._run(["git", "-C", str(work), "rev-parse", "--abbrev-ref", "HEAD"]).strip() or "main")
            self._run(["git", "-C", str(work), "checkout", "-b", branch])
            # Clobber-protected 3-way merge against the target's current files (R4): an operator's
            # edit to a generated file is preserved (the fresh draft is routed to .proposed/),
            # orphaned outputs are pruned, all tracked in .sre/manifest.yaml.
            merge_tree(tree, work)
            self._run(["git", "-C", str(work), "add", "-A"])
            if not self._run(["git", "-C", str(work), "status", "--porcelain"]).strip():
                raise ForgePublishError("nothing to publish: the KB already matches the target branch")
            self._run(["git", "-C", str(work), *_GIT_USER, "commit", "-m", title])
            self._run(["git", "-C", str(work), "push", "-u", "origin", branch])
        resp = self._post(
            f"https://api.github.com/repos/{owner}/{repo}/pulls",
            {"title": title, "head": branch, "base": base, "body": body},
            token,
        )
        return resp.get("html_url") or resp.get("url") or f"opened PR on {owner}/{repo}:{branch}"
