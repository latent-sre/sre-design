"""§7.3 — make the non-circular contract testable. A corpus of *planted* artifacts whose
claims an LLM enrichment could plausibly assert but the cited code does NOT support; the
deterministic challenge gate must reject/downgrade each. The dual of `resiliency-skills`'
`examples/malicious/`: without this, the grounding gate can silently rot into the
self-consistency check it was built to avoid (see `validation/challenge.py` docstring).

These fixtures exercise the *challenge* layer (grounding a claim against its cited bytes),
not provenance — the excerptHash is a placeholder on purpose.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sre_kb.validation.challenge import GroundingChallenger, apply_challenge_gating, challenge_doc

CORPUS = Path(__file__).parent / "fixtures" / "adversarial-llm"

# filename -> the status the challenge gate must force the planted (status: verified) artifact to.
_EXPECTED = {
    "alert-fabricated-detection.yaml": "needs-review",     # detection string never logged -> unsupported
    "alert-claims-swallow-but-rethrows.yaml": "rejected",  # cited code rethrows -> contradicted
    "resiliency-fabricated-breaker.yaml": "needs-review",  # no breaker at the cited lines -> unsupported
    "flow-ghost-handler.yaml": "needs-review",             # handler absent at the cited line -> unsupported
    "flow-grounded-control.yaml": "verified",              # control: grounded -> survives
}


def _read_lines(rel: str) -> list[str]:
    return (CORPUS / rel).read_text(encoding="utf-8").splitlines(keepends=True)


@pytest.mark.parametrize("name, expected", sorted(_EXPECTED.items()))
def test_adversarial_llm_claims_are_caught(name: str, expected: str) -> None:
    doc = yaml.safe_load((CORPUS / name).read_text(encoding="utf-8"))
    verdicts = challenge_doc(doc, _read_lines, GroundingChallenger())
    assert verdicts, f"{name}: expected a challengeable claim to be extracted"
    new_status, _ = apply_challenge_gating(doc["status"], verdicts)
    assert new_status == expected, f"{name}: verdicts={[v.verdict for v in verdicts]} -> {new_status}"


def test_corpus_actually_contains_adversarial_cases() -> None:
    # Guard against the corpus quietly degrading to all-control (which would make the gate look
    # effective while testing nothing).
    downgraded = [n for n, s in _EXPECTED.items() if s != "verified"]
    assert len(downgraded) >= 3 and "rejected" in _EXPECTED.values()
