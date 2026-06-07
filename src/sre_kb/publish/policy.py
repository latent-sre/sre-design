"""Publish-time policy: a fail-closed target-repo allowlist.

Before Phase 1, `open_pr` would push to whatever `--sre-repo` named, relying entirely on the
ambient token's scope (HYBRID-PLAN.md §4 "Publish path"). A leaked/over-scoped token could
therefore open a PR into any repo it could reach. The allowlist makes the *engine* — not just
the token — gate the destination.

Sources, unioned: `publish.allowed_repos` in config + the `SRE_KB_ALLOWED_REPOS` env var
(comma/space separated). Entries are normalised to `owner/repo`. Fail-closed: a LIVE publish
to a repo not on the list (or with no list configured) is refused. Dry-run is never gated —
it writes nothing outside the work dir.
"""

from __future__ import annotations

import os
import re

from sre_kb.config import load_config
from sre_kb.publish.forge.base import ForgePublishError
from sre_kb.publish.forge.github import parse_repo


def allowed_repos() -> set[str]:
    cfg = (load_config().get("publish") or {}).get("allowed_repos") or []
    env = re.split(r"[,\s]+", os.environ.get("SRE_KB_ALLOWED_REPOS", "").strip())
    out: set[str] = set()
    for entry in [*cfg, *env]:
        if not entry:
            continue
        try:
            owner, repo = parse_repo(str(entry))
        except ForgePublishError:
            continue
        out.add(f"{owner}/{repo}")
    return out


def enforce_repo_allowlist(sre_repo: str) -> str:
    """Return the normalised `owner/repo` if allowed; raise ForgePublishError otherwise."""
    owner, repo = parse_repo(sre_repo)
    target = f"{owner}/{repo}"
    allowed = allowed_repos()
    if not allowed:
        raise ForgePublishError(
            "live publish refused: no target-repo allowlist configured. Set publish.allowed_repos "
            "in config or SRE_KB_ALLOWED_REPOS=owner/repo (or use --dry-run)."
        )
    if target not in allowed:
        raise ForgePublishError(
            f"live publish refused: {target} is not in the allowlist {sorted(allowed)}"
        )
    return target
