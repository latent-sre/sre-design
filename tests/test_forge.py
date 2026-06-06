"""GitHubForge: git + REST publish path, exercised end-to-end with injected seams
(no token, no network). Verifies the git sequence, the PR payload, and token redaction."""

from __future__ import annotations

import pytest

from sre_kb.publish.forge import get_forge
from sre_kb.publish.forge.base import ForgePublishError
from sre_kb.publish.forge.github import GitHubForge, _redact, parse_repo


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
        return "main\n" if "rev-parse" in cmd else ""

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


def test_get_forge_defaults_to_local_for_unknown():
    assert get_forge("nope").name == "local"
    assert get_forge("github").name == "github"
