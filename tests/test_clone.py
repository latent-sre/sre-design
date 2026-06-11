"""The clone stage's URL arm (DESIGN.md: "cloned locally by the engine, or an existing local
path"): a git URL shallow-clones into the run workspace; local paths pass through."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sre_kb.clone import ensure_local, is_git_url


def test_url_detection():
    assert is_git_url("https://github.com/acme/orders.git")
    assert is_git_url("git@github.com:acme/orders.git")
    assert is_git_url("ssh://git@host/acme/orders.git")
    assert is_git_url("file:///tmp/repo")
    assert not is_git_url("/home/user/orders")
    assert not is_git_url("../orders")


def test_local_path_passes_through(tmp_path):
    assert ensure_local(str(tmp_path), tmp_path / "unused") == tmp_path.resolve()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    repo.mkdir()
    (repo / "manifest.yml").write_text("applications:\n- name: cloned-svc\n", encoding="utf-8")
    for cmd in (["git", "init", "-q"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)  # noqa: S603
    return repo


def test_git_url_is_shallow_cloned_and_idempotent(tmp_path):
    repo = _make_repo(tmp_path)
    dest = tmp_path / "work" / "target"
    out = ensure_local(repo.as_uri(), dest)
    assert out == dest and (dest / "manifest.yml").is_file()
    marker = dest / "marker"
    marker.touch()
    assert ensure_local(repo.as_uri(), dest) == dest  # reused, not re-cloned
    assert marker.exists()


def test_failed_clone_raises_with_the_git_error(tmp_path):
    with pytest.raises(RuntimeError, match="clone failed"):
        ensure_local("file:///nonexistent/nowhere", tmp_path / "dest")


def test_run_pipeline_accepts_a_git_url(tmp_path):
    from sre_kb.pipeline import run as run_pipeline

    repo = _make_repo(tmp_path)
    r = run_pipeline(repo.as_uri(), work_root=str(tmp_path / "w"), run_id="cl",
                     to_stage="validate")
    assert r.docs > 0
    assert (r.root / "target" / "manifest.yml").is_file()  # cloned inside the run workspace
