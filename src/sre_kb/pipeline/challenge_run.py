"""Live challenge loop: drive the judgment-call worklist through an external LLM oracle and
emit a verdicts file that `challenge-apply` re-gates (monotonic, downgrade-only).

Architectural invariant: the engine still embeds no LLM client. The oracle is an *external
process* the operator configures — the same neutrality seam as `Forge` (SCM-neutral) and the
unset model (LLM-neutral). `SubprocessOracle` is exactly the `client: Callable[[str], str]`
hook that `LLMChallenger` already anticipates; the difference is granularity — the worklist
item carries a richer, untrusted-framed prompt (the full context pack) than
`LLMChallenger.build_prompt` rebuilds from a bare excerpt, so the live loop reuses that
prompt rather than discarding it. Reply parsing is the *same* `parse_verdict_reply` both
paths share, so they adjudicate identically.

Safety carries over unchanged: verdicts only ever feed `apply_challenge_gating`, which can
lower confidence but never raise it. A misbehaving oracle's worst case is a false downgrade
(a human re-checks something fine) or — because the prompt frames the cited code as UNTRUSTED
data — an injection attempt it must ignore. An empty/garbled/negating reply parses to
`indeterminate`, never a false `supported`. It can never promote an artifact to `verified`.
"""

from __future__ import annotations

from typing import Callable

from sre_kb.llm.provider import SubprocessProvider
from sre_kb.validation.challenge import parse_verdict_reply

# The subprocess oracle is now one impl of the unified `LLMProvider` seam (`llm/provider.py`); kept
# here as a back-compat alias so existing callers (`cli.challenge_run`, tests) are unchanged.
SubprocessOracle = SubprocessProvider


def run_worklist(worklist: dict, oracle: Callable[[str], str], *, oracle_id: str = "oracle") -> dict:
    """Adjudicate every worklist item through `oracle`, returning a verdicts document in the
    shape `challenge-apply` consumes. Each item already carries a self-contained,
    untrusted-framed `prompt`; we attach the verdict the shared parser reads from the reply.
    `oracle_id` is recorded once at the document level (audit trail of who adjudicated) so
    each verdict stays the documented {artifact, claimId, verdict, reason} shape."""
    verdicts = []
    for item in worklist.get("items", []):
        verdict, reason = parse_verdict_reply(oracle(item["prompt"]))
        verdicts.append(
            {
                "artifact": item["artifact"],
                "claimId": item["claimId"],
                "verdict": verdict,
                "reason": reason,
            }
        )
    return {
        "schema": "challenge.verdicts/v1",
        "runId": worklist.get("runId"),
        "oracle": oracle_id,
        "verdicts": verdicts,
    }
