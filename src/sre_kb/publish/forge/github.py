"""GitHub forge — git + GitHub REST API (token from env). Live publish is deferred to a
later phase; this raises until then so --dry-run is the supported path. The engine does
NOT use this session's MCP tools (those aren't available to a standalone engine)."""

from __future__ import annotations

from pathlib import Path


class GitHubForge:
    name = "github"

    def open_pr(self, tree: Path, *, sre_repo: str, branch: str, title: str, body: str) -> str:
        raise NotImplementedError(
            "Live GitHub publish is deferred (P3/P4). Use --dry-run to stage the PR tree."
        )
