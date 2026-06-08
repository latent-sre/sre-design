"""Challenge-pass validator: adversarial grounding of claims against cited evidence,
with monotonic downgrade-only gating."""

from __future__ import annotations

import json
from pathlib import Path

from sre_kb.pipeline import run as run_pipeline
from sre_kb.validation.challenge import (
    Claim,
    GroundingChallenger,
    LLMChallenger,
    Verdict,
    apply_challenge_gating,
    challenge_doc,
    extract_claims,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def test_grounding_supported_unsupported_contradicted():
    c = GroundingChallenger()
    claim = Claim("x", "d", 0, needle="failed to publish", refute="throw")
    assert c.adjudicate(claim, 'log.error("failed to publish event");').verdict == "supported"
    assert c.adjudicate(claim, 'log.error("unrelated");').verdict == "unsupported"
    assert c.adjudicate(claim, 'log.error("failed to publish"); throw e;').verdict == "contradicted"


def test_extract_claims_per_kind():
    alert = {"kind": "Alert", "spec": {"signalSource": "log-pattern",
             "expr": {"splunk": 'index=app "boom happened" | stats'}}, "evidence": [{}]}
    ac = extract_claims(alert)
    assert ac[0].needle == "boom happened" and ac[0].refute == "throw"
    flow = {"kind": "Flow", "spec": {"trigger": {"entrypoint": "a.b.C#handleX"}}, "evidence": [{}]}
    assert extract_claims(flow)[0].needle == "handleX"
    assert extract_claims({"kind": "Alert", "spec": {}, "evidence": []}) == []  # no evidence -> no claims


def test_gating_is_monotonic_downgrade_only():
    assert apply_challenge_gating("verified", [Verdict("x", "supported", "")])[0] == "verified"
    assert apply_challenge_gating("verified", [Verdict("x", "unsupported", "")])[0] == "needs-review"
    assert apply_challenge_gating("verified", [Verdict("x", "contradicted", "")])[0] == "rejected"
    # never upgrades
    assert apply_challenge_gating("needs-review", [Verdict("x", "supported", "")])[0] == "needs-review"
    assert apply_challenge_gating("rejected", [Verdict("x", "supported", "")])[0] == "rejected"


def test_unknown_verdict_is_indeterminate_not_lenient():
    """An out-of-vocab verdict must not be treated as the lenient 'supported' (a silent false pass);
    it is normalized to indeterminate (non-blocking), and a real contradiction still drives the worst
    case."""
    assert apply_challenge_gating("verified", [Verdict("x", "banana", "")])[0] == "verified"
    assert apply_challenge_gating(
        "verified", [Verdict("x", "banana", ""), Verdict("y", "contradicted", "")]
    )[0] == "rejected"


def test_challenge_doc_reads_evidence_and_flags_tamper():
    doc = {"kind": "Flow", "spec": {"trigger": {"entrypoint": "a.b.C#createOrder"}},
           "evidence": [{"path": "X.java", "lines": {"start": 1, "end": 1}}]}
    reads = {"X.java": ["public void createOrder() {\n"]}
    assert challenge_doc(doc, lambda p: reads[p], GroundingChallenger())[0].verdict == "supported"
    doc["spec"]["trigger"]["entrypoint"] = "a.b.C#ghostMethod"  # claim not grounded
    assert challenge_doc(doc, lambda p: reads[p], GroundingChallenger())[0].verdict == "unsupported"


def test_llm_challenger_defers_offline_and_frames_untrusted():
    assert LLMChallenger().adjudicate(Claim("x", "d", 0, needle="n"), "code").verdict == "indeterminate"
    stub = LLMChallenger(client=lambda prompt: "contradicted: not present")
    assert stub.adjudicate(Claim("x", "d", 0), "e").verdict == "contradicted"
    assert "UNTRUSTED" in stub.build_prompt(Claim("x", "desc", 0), "code")


def test_engine_output_survives_its_own_adversarial_pass(tmp_path):
    """The deterministic scaffold must pass the deterministic challenger — every claim grounded."""
    r = run_pipeline(str(FIXTURE), work_root=str(tmp_path), run_id="ch", to_stage="validate")
    report = json.loads((r.root / "reports" / "validation_report.json").read_text())
    challenged = [rec for rec in report["records"] if rec["challenge"]]
    assert challenged, "expected some artifacts to carry challengeable claims"
    for rec in challenged:
        assert all(v["verdict"] == "supported" for v in rec["challenge"]), rec
