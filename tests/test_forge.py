"""GitHubForge: git + REST publish path, exercised end-to-end with injected seams
(no token, no network). Verifies the git sequence, the PR payload, and token redaction."""

from __future__ import annotations

import subprocess

import pytest

from sre_kb.publish.forge import get_forge
from sre_kb.publish.forge.base import ForgePublishError
from sre_kb.publish.forge.github import GitHubForge, _default_post, _default_run, _redact, parse_repo


def test_parse_repo_variants():
    assert parse_repo("owner/name") == ("owner", "name")
    assert parse_repo("https://github.com/owner/name") == ("owner", "name")
    assert parse_repo("https://github.com/owner/name.git") == ("owner", "name")
    assert parse_repo("git@github.com:owner/name.git") == ("owner", "name")
    with pytest.raises(ForgePublishError):
        parse_repo("nope")


def test_open_pr_requires_token(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(ForgePublishError):
        GitHubForge().open_pr(tmp_path, sre_repo="o/r", branch="b", title="t", body="x")


def test_open_pr_drives_git_and_rest(tmp_path):
    (tmp_path / "catalog").mkdir()
    (tmp_path / "catalog" / "x.yaml").write_text("a: 1\n")
    calls: list[list[str]] = []

    def runner(cmd):
        calls.append(cmd)
        if "rev-parse" in cmd:
            return "main\n"
        if "--porcelain" in cmd:
            return " M catalog/x.yaml\n"
        return ""

    posted: dict = {}

    def http_post(url, payload, token):
        posted.update(url=url, payload=payload, token=token)
        return {"html_url": "https://github.com/o/r/pull/7"}

    forge = GitHubForge(runner=runner, http_post=http_post, token="T")
    ref = forge.open_pr(tmp_path, sre_repo="o/r", branch="sre-kb/update", title="SRE KB: svc", body="body")

    assert ref == "https://github.com/o/r/pull/7"
    joined = [" ".join(c) for c in calls]
    assert any("clone --depth 1" in c for c in joined)
    assert any("checkout -b sre-kb/update" in c for c in joined)
    assert any("commit -m SRE KB: svc" in c for c in joined)
    assert any(c.endswith("push -u origin sre-kb/update") for c in joined)
    assert posted["url"] == "https://api.github.com/repos/o/r/pulls"
    assert posted["payload"] == {"title": "SRE KB: svc", "head": "sre-kb/update", "base": "main", "body": "body"}
    assert posted["token"] == "T"


def test_redact_hides_token():
    red = " ".join(_redact(["git", "clone", "https://x-access-token:SECRET@github.com/o/r.git", "d"]))
    assert "SECRET" not in red and "x-access-token:***@" in red


def test_default_post_wraps_http_error_without_leaking_token(monkeypatch):
    """A non-2xx GitHub response must surface as ForgePublishError (the Forge contract), and the
    token must not appear in the surfaced error."""
    import urllib.error

    from sre_kb.publish.forge import github

    def boom(req, *a, **k):
        raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable Entity", {}, None)

    monkeypatch.setattr(github.urllib.request, "urlopen", boom)
    with pytest.raises(ForgePublishError) as ei:
        _default_post("https://api.github.com/repos/o/r/pulls", {"title": "t"}, "SECRETTOKEN")
    assert "422" in str(ei.value)
    assert "SECRETTOKEN" not in str(ei.value)


def test_default_run_times_out_as_forge_error(monkeypatch):
    """A stalled git subprocess is bounded and surfaced as ForgePublishError, not an indefinite hang."""
    from sre_kb.publish.forge import github

    def slow(cmd, *a, **k):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=k.get("timeout"))

    monkeypatch.setattr(github.subprocess, "run", slow)
    with pytest.raises(ForgePublishError) as ei:
        _default_run(["git", "clone", "--depth", "1", "https://github.com/o/r.git", "d"])
    assert "timed out" in str(ei.value)


def test_get_forge_defaults_to_local_for_unknown():
    assert get_forge("nope").name == "local"
    assert get_forge("github").name == "github"


def _seam_runner(calls: list[list[str]] | None = None):
    def runner(cmd):
        if calls is not None:
            calls.append(cmd)
        if "rev-parse" in cmd:
            return "main\n"
        if "--porcelain" in cmd:
            return " M x.yaml\n"
        return ""

    return runner


def test_open_pr_keeps_token_out_of_argv(tmp_path):
    (tmp_path / "x.yaml").write_text("a: 1\n")
    calls: list[list[str]] = []
    forge = GitHubForge(runner=_seam_runner(calls), http_post=lambda *a: {"html_url": "u"}, token="SECRETTOKEN123")

    assert forge.open_pr(tmp_path, sre_repo="o/r", branch="b", title="t", body="x") == "u"
    flat = " ".join(" ".join(c) for c in calls)
    assert "SECRETTOKEN123" not in flat            # token is never on the git command line
    assert "https://github.com/o/r.git" in flat    # remote URL is tokenless


def test_open_pr_rejects_unsafe_branch_name(tmp_path):
    """A branch starting with '-' would be parsed by git as an option (arg-injection); '..' is not
    valid ref content. The guard must reject before any git runs."""
    forge = GitHubForge(
        runner=lambda cmd: (_ for _ in ()).throw(AssertionError("git must not run")),
        token="T",
    )
    for bad in ("-x", "a..b", "feat;rm -rf", "white space"):
        with pytest.raises(ForgePublishError):
            forge.open_pr(tmp_path, sre_repo="o/r", branch=bad, title="t", body="x")


def test_open_pr_allowlist_blocks_unlisted_repo(tmp_path):
    def runner(cmd):
        raise AssertionError("git must not run when the target repo is blocked")

    forge = GitHubForge(runner=runner, token="T", allowed_repos=["someone/else"])
    with pytest.raises(ForgePublishError):
        forge.open_pr(tmp_path, sre_repo="o/r", branch="b", title="t", body="x")


def test_open_pr_allowlist_allows_listed_repo(tmp_path):
    (tmp_path / "x.yaml").write_text("a: 1\n")
    forge = GitHubForge(
        runner=_seam_runner(), http_post=lambda *a: {"html_url": "u"}, token="T",
        allowed_repos=["https://github.com/o/r.git"],  # URL form normalizes to o/r
    )
    assert forge.open_pr(tmp_path, sre_repo="o/r", branch="b", title="t", body="x") == "u"
