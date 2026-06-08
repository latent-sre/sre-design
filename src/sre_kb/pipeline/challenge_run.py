"""Live challenge loop: drive the judgment-call worklist through an external LLM oracle
and emit a verdicts file that `challenge-apply` re-gates (monotonic, downgrade-only).

Architectural invariant: the engine still never embeds an LLM client. The oracle is an
*external process* the operator configures — the same neutrality seam as `Forge`
(SCM-neutral) and the unset model (LLM-neutral). Point it at the Copilot/Claude CLI and
the loop runs end-to-end; configure nothing and it stays deferred (every claim
`indeterminate` → a human reviews), exactly the offline behaviour today.

Safety carries over unchanged: verdicts only ever feed `apply_challenge_gating`, which
can lower confidence but never raise it. A misbehaving oracle's worst case is a false
downgrade (a human re-checks something fine) or — because the worklist prompt frames the
cited code as UNTRUSTED data — an injection attempt it must ignore. It can never promote
an artifact to `verified`.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from typing import Callable

# contradicted/unsupported listed before supported so the substring in "unsupported"
# can't be mistaken for a "supported" verdict; \b anchors keep them whole words anyway.
_VERDICT_RE = re.compile(r"\b(contradicted|unsupported|supported)\b")


def parse_reply(raw: str) -> tuple[str, str]:
    """Map a free-text oracle reply to (verdict, reason). Conservative by construction:
    anything we can't read as a verdict is `indeterminate` (deferred to a human), never a
    pass — so an empty/garbled/timed-out oracle can only ever defer, not approve."""
    text = (raw or "").strip()
    match = _VERDICT_RE.search(text.lower())
    if not match:
        return "indeterminate", "unparseable oracle reply; deferred to human"
    reason = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return match.group(1), (reason[:200] or "oracle adjudication")


class SubprocessOracle:
    """An oracle that shells out to an operator-configured command. The prompt is fed on
    STDIN (never argv) so untrusted target code in the pack can't break out into the
    command line; the verdict is read from STDOUT."""

    def __init__(self, cmd: str | list[str], *, timeout: float = 120.0):
        self.argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
        if not self.argv:
            raise ValueError("empty oracle command")
        self.timeout = timeout
        self.id = f"subprocess:{self.argv[0].rsplit('/', 1)[-1]}"

    def __call__(self, prompt: str) -> str:
        try:
            proc = subprocess.run(
                self.argv,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""  # parse_reply -> indeterminate (deferred), never a false pass
        return proc.stdout


def run_worklist(worklist: dict, oracle: Callable[[str], str], *, oracle_id: str = "oracle") -> dict:
    """Adjudicate every worklist item through `oracle`, returning a verdicts document in
    the shape `challenge-apply` consumes. Each item already carries a self-contained,
    untrusted-framed `prompt`; we attach the verdict the oracle returns."""
    verdicts = []
    for item in worklist.get("items", []):
        verdict, reason = parse_reply(oracle(item["prompt"]))
        verdicts.append(
            {
                "artifact": item["artifact"],
                "claimId": item["claimId"],
                "verdict": verdict,
                "reason": reason,
                "oracle": oracle_id,
            }
        )
    return {"schema": "challenge.verdicts/v1", "runId": worklist.get("runId"), "verdicts": verdicts}
