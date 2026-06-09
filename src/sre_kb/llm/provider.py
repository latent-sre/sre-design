"""The `LLMProvider` seam — the LLM-transport-neutral seam (mirrors the SCM-neutral `Forge` seam).

Standing decision (`docs/VERTEX-LLM-PROVIDER-CASE.md`): the only org-approved transport today is
enterprise GitHub Copilot, IDE-only, so the engine stays **model-free by default** — it emits the
scan-worklist and a human/Copilot writes the outputs (the file exchange). This module is the *seam*
that keeps that default while making a future programmatic transport (first candidate: Google Vertex,
deferred pending the business case) a drop-in impl rather than a rewrite.

The trust boundary never moves: a provider is a **pointer-generator**. Whatever it returns, the engine
re-grounds at the cited bytes and gates it — an automated call can never assert a verdict the engine
trusts. Determinism is preserved by `CachingProvider` (responses keyed by prompt-hash), so a
programmatic provider replays from cache in CI; only an explicit refresh hits the model.

Impls:
  - `CopilotFileProvider`  — the default. Model-free: it does not call a model; the engine defers to
                             the manual worklist→verdicts file exchange.
  - `SubprocessProvider`   — exec an operator-configured CLI (the existing `--oracle` seam).
  - `VertexProvider`       — deferred slot for Vertex/Gemini in-tenant; raises until the case lands.
  - `CachingProvider`      — wraps any provider with a prompt-hash response cache (reproducibility).
"""

from __future__ import annotations

import hashlib
import shlex
import subprocess
from pathlib import Path
from typing import Protocol, runtime_checkable


class LLMUnavailable(Exception):
    """Raised when a provider cannot synchronously answer — e.g. the default file-exchange provider,
    which defers to the manual worklist loop rather than calling a model."""


@runtime_checkable
class LLMProvider(Protocol):
    """The seam every transport satisfies. `complete` is the single pointer-generator call; a provider
    is also callable so it drops straight into `run_worklist(oracle=...)` as the oracle."""

    id: str
    interactive: bool  # True = the manual file exchange (no synchronous model call)

    def complete(self, prompt: str) -> str: ...


class CopilotFileProvider:
    """The default, model-free provider: the engine emits the scan-worklist and a human runs the
    skills in the IDE (enterprise Copilot) and writes the output files. There is no synchronous model
    call, so `complete` raises — callers detect this via `interactive` and defer to the file loop."""

    id = "copilot-file-exchange"
    interactive = True

    def complete(self, prompt: str) -> str:
        raise LLMUnavailable(
            "the default Copilot file-exchange provider does not call a model — run the scan-worklist "
            "skills in the IDE and ingest the output files, or configure a programmatic llm.provider"
        )

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)


class SubprocessProvider:
    """Exec an operator-configured command (the Copilot/Claude CLI). The prompt is fed on STDIN (never
    argv), so untrusted target code in the pack can't break out into the command line; the completion
    is read from STDOUT. A failed/timed-out call returns "" — the verdict parser reads that as
    `indeterminate` (deferred), never a false pass."""

    interactive = False

    def __init__(self, cmd: str | list[str], *, timeout: float = 120.0):
        self.argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        if not self.argv:
            raise ValueError("empty provider command")
        self.timeout = timeout
        self.id = f"subprocess:{self.argv[0].rsplit('/', 1)[-1]}"

    def complete(self, prompt: str) -> str:
        try:
            proc = subprocess.run(
                self.argv, input=prompt, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if proc.returncode != 0:
            # A failing oracle's stdout (an error banner, a partial answer before the crash) is
            # not an answer — returning it would let CachingProvider cache the failure forever.
            return ""
        return proc.stdout

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)


class VertexProvider:
    """Deferred slot for Google Vertex AI (Gemini) in-tenant — the first programmatic transport
    candidate. Kept as a named impl so the seam is *ready*, but it raises until the business case in
    `docs/VERTEX-LLM-PROVIDER-CASE.md` is approved (it must not call out unilaterally)."""

    id = "vertex"
    interactive = False

    def __init__(self, *_, **__):
        pass

    def complete(self, prompt: str) -> str:
        raise NotImplementedError(
            "the Vertex provider is a deferred seam — approve docs/VERTEX-LLM-PROVIDER-CASE.md and "
            "implement the in-tenant client before enabling llm.provider=vertex"
        )

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)


class CachingProvider:
    """Wrap any provider with a prompt-hash response cache (reproducibility, per the case doc). The
    cache is content-addressed: sha256(prompt) -> response file under `cache_dir`. A cache hit never
    calls the inner provider, so CI replays deterministically; deleting the file forces a refresh."""

    def __init__(self, inner: LLMProvider, cache_dir: str | Path):
        self.inner = inner
        self.id = f"cached:{inner.id}"
        self.interactive = getattr(inner, "interactive", False)
        self.dir = Path(cache_dir)

    def _path(self, prompt: str) -> Path:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return self.dir / f"{digest}.txt"

    def complete(self, prompt: str) -> str:
        path = self._path(prompt)
        if path.exists():
            return path.read_text(encoding="utf-8")
        response = self.inner.complete(prompt)
        if response:
            # An empty response is the inner provider's failure signal (timeout/exec error,
            # parsed as `indeterminate`) — caching it would make one transient failure a
            # permanent verdict; leave the slot empty so a re-run retries the oracle.
            self.dir.mkdir(parents=True, exist_ok=True)
            path.write_text(response, encoding="utf-8")
        return response

    def __call__(self, prompt: str) -> str:
        return self.complete(prompt)


_PROVIDERS = {
    "copilot": CopilotFileProvider,
    "copilot-file-exchange": CopilotFileProvider,
    "vertex": VertexProvider,
}


def make_provider(config: dict | None = None, *, command: str | None = None) -> LLMProvider:
    """Build the configured provider from the `llm` config block (default: the model-free
    `CopilotFileProvider`). `command` (e.g. the CLI `--oracle`) selects the subprocess provider. When
    `llm.cache_dir` is set, the provider is wrapped in a prompt-hash `CachingProvider`.

    Config:
        llm:
          provider: copilot | subprocess | vertex   # default copilot (model-free)
          command: "copilot -p"                      # for provider=subprocess
          cache_dir: .work/llm-cache                 # optional prompt-hash cache
          timeout: 120
    """
    cfg = (config or {}).get("llm") or {}
    name = (cfg.get("provider") or ("subprocess" if command or cfg.get("command") else "copilot")).lower()
    timeout = float(cfg.get("timeout", 120.0))

    if name == "subprocess":
        cmd = command or cfg.get("command")
        if not cmd:
            raise ValueError("llm.provider=subprocess requires a command (llm.command or --oracle)")
        provider: LLMProvider = SubprocessProvider(cmd, timeout=timeout)
    else:
        factory = _PROVIDERS.get(name)
        if factory is None:
            raise ValueError(f"unknown llm.provider: {name!r}")
        provider = factory()

    cache_dir = cfg.get("cache_dir")
    return CachingProvider(provider, cache_dir) if cache_dir else provider
