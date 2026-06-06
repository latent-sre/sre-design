"""GitHub forge: git (clone -> branch -> sync tree -> commit -> push) + the REST API to
open the PR. Token comes from GITHUB_TOKEN/GH_TOKEN. The engine does NOT use this
session's MCP tools (those aren't available to a standalone engine in CI).

The git runner and the REST POST are injectable seams so the whole flow is unit-tested
without a token or network; the defaults shell out to `git` and urllib.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from sre_kb.publish.forge.base import ForgePublishError

_GIT_USER = ["-c", "user.email=sre-kb@users.noreply.github.com", "-c", "user.name=sre-kb"]


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
    return [re.sub(r"x-access-token:[^@]+@", "x-access-token:***@", c) for c in cmd]


def _default_run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
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
    with urllib.request.urlopen(req) as r:  # noqa: S310
        return json.loads(r.read().decode())


def _sync_tree(tree: Path, work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for item in tree.iterdir():
        if item.name == ".git":
            continue
        dest = work / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)


class GitHubForge:
    name = "github"

    def __init__(
        self,
        *,
        runner: Callable[[list[str]], str] | None = None,
        http_post: Callable[[str, dict, str], dict] | None = None,
        token: str | None = None,
    ):
        self._run = runner or _default_run
        self._post = http_post or _default_post
        self._token = token

    def open_pr(self, tree: Path, *, sre_repo: str, branch: str, title: str, body: str) -> str:
        token = self._token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            raise ForgePublishError("set GITHUB_TOKEN to publish live (or use --dry-run)")
        owner, repo = parse_repo(sre_repo)
        remote = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "repo"
            self._run(["git", "clone", "--depth", "1", remote, str(work)])
            base = (self._run(["git", "-C", str(work), "rev-parse", "--abbrev-ref", "HEAD"]).strip() or "main")
            self._run(["git", "-C", str(work), "checkout", "-b", branch])
            _sync_tree(tree, work)
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
