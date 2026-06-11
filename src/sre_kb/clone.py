"""Materialize a scan target (the pipeline's `clone` stage made real for URLs).

DESIGN.md promises "the target repo is cloned locally by the engine (or an existing local
path passed in)"; until now only the local-path arm existed. A git URL (`https://`, `ssh://`,
`git@`, or `file://`) is shallow-cloned into the run's workspace; a local path passes through
untouched.

Credential posture (§9.3 #5): the engine handles NO credentials — the clone relies on ambient
git auth (the CI checkout token, the operator's agent). `--depth 1` because the scan reads the
working tree, never history; `--` stops option injection from a URL-shaped argument.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_GIT_URL = re.compile(r"^(https?://|ssh://|git@|file://)")
_CLONE_TIMEOUT_S = 600


def is_git_url(target: str) -> bool:
    return bool(_GIT_URL.match(target))


def ensure_local(target: str, clone_dest: Path) -> Path:
    """A local path resolves to itself; a git URL is shallow-cloned to `clone_dest`
    (idempotent per run: an existing non-empty `clone_dest` is reused)."""
    if not is_git_url(target):
        return Path(target).resolve()
    if clone_dest.is_dir() and any(clone_dest.iterdir()):
        return clone_dest  # already materialized for this run
    clone_dest.parent.mkdir(parents=True, exist_ok=True)
    # argv is fixed except the operator-supplied target (a CLI argument, trusted input by
    # precedent); `--` prevents it from being parsed as an option. No shell is involved.
    proc = subprocess.run(  # noqa: S603
        ["git", "clone", "--quiet", "--depth", "1", "--", target, str(clone_dest)],  # noqa: S607
        capture_output=True, text=True, check=False, timeout=_CLONE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"clone failed for {target}: {proc.stderr.strip()[:500] or 'unknown git error'}")
    return clone_dest
