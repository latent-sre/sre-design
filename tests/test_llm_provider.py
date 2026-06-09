"""LLMProvider seam (groundwork): model-free default, deferred Vertex slot, prompt-hash caching."""

from __future__ import annotations

import pytest

from sre_kb.llm.provider import (
    CachingProvider,
    CopilotFileProvider,
    LLMProvider,
    LLMUnavailable,
    SubprocessProvider,
    VertexProvider,
    make_provider,
)


class _CountingProvider:
    id = "counting"
    interactive = False

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return f"resp:{prompt}"


def test_default_provider_is_model_free():
    p = make_provider()  # no config -> the Copilot file exchange
    assert isinstance(p, CopilotFileProvider) and p.interactive is True
    assert isinstance(p, LLMProvider)
    with pytest.raises(LLMUnavailable):
        p.complete("anything")  # the engine does not call a model by default


def test_vertex_is_a_deferred_slot():
    p = make_provider({"llm": {"provider": "vertex"}})
    assert isinstance(p, VertexProvider)
    with pytest.raises(NotImplementedError, match="VERTEX-LLM-PROVIDER-CASE"):
        p.complete("p")


def test_subprocess_provider_selected_by_command_or_config():
    assert isinstance(make_provider(command="cat"), SubprocessProvider)
    assert isinstance(make_provider({"llm": {"provider": "subprocess", "command": "cat"}}),
                      SubprocessProvider)
    assert make_provider(command="cat").complete("hello") == "hello"  # cat echoes stdin
    with pytest.raises(ValueError):
        make_provider({"llm": {"provider": "subprocess"}})  # no command


def test_prompt_hash_cache_replays_without_recalling(tmp_path):
    inner = _CountingProvider()
    cached = CachingProvider(inner, tmp_path)
    assert cached.complete("same") == "resp:same"
    assert cached.complete("same") == "resp:same"   # served from cache
    assert inner.calls == 1                          # inner called once, not twice
    cached.complete("other")
    assert inner.calls == 2                          # a different prompt does call through
    # the cache is content-addressed on disk (sha256(prompt).txt), so it persists across runs
    assert any(p.suffix == ".txt" for p in tmp_path.iterdir())


def test_transient_failure_is_not_cached(tmp_path):
    """SubprocessProvider returns "" on timeout/exec error (parsed as `indeterminate`). Caching
    that would turn one transient oracle failure into a permanent verdict for the prompt."""

    class _FlakyProvider:
        id = "flaky"
        interactive = False
        calls = 0

        def complete(self, prompt: str) -> str:
            self.calls += 1
            return "" if self.calls == 1 else "supported"

    cached = CachingProvider(_FlakyProvider(), tmp_path)
    assert cached.complete("p") == ""           # the failure is returned…
    assert cached.complete("p") == "supported"  # …but the retry reaches the oracle
    assert cached.complete("p") == "supported"  # and the good response IS cached
    assert cached.inner.calls == 2


def test_make_provider_wraps_in_cache_when_configured(tmp_path):
    p = make_provider({"llm": {"provider": "subprocess", "command": "cat",
                               "cache_dir": str(tmp_path)}})
    assert isinstance(p, CachingProvider)
    assert p.complete("x") == "x" and (tmp_path).exists()


def test_unknown_provider_rejected():
    with pytest.raises(ValueError, match="unknown llm.provider"):
        make_provider({"llm": {"provider": "nope"}})


def test_subprocess_oracle_alias_is_the_provider():
    from sre_kb.pipeline.challenge_run import SubprocessOracle
    assert SubprocessOracle is SubprocessProvider


def test_subprocess_nonzero_exit_is_a_failure_not_an_answer():
    """A failing oracle's stdout (an error banner before exit 1) must read as the failure signal
    "" — otherwise CachingProvider would cache the error text as the permanent answer."""
    p = SubprocessProvider(["sh", "-c", "echo rate limit exceeded; exit 1"])
    assert p.complete("x") == ""
