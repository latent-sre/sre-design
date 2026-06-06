"""§7.4 — the shared signature library + re-derivation. A signature fires on the real pattern
(across Java/Spring and .NET/Polly), not on a bare keyword, and the challenge gate re-derives a
ResiliencyPattern claim by asking "does the signature fire at the cited location?".
"""

from __future__ import annotations

from sre_kb.signatures import concerns, fires, rederive
from sre_kb.validation.challenge import GroundingChallenger, extract_claims


def test_circuit_breaker_signature_fires_across_stacks() -> None:
    assert fires("circuit-breaker", '@CircuitBreaker(name="inv", fallbackMethod="fb")')   # resilience4j
    assert fires("circuit-breaker", "_breaker = Policy.Handle<Exception>().CircuitBreakerAsync(5, t);")  # Polly
    assert fires("circuit-breaker", "resilience4j.circuitbreaker.instances.inventory.slidingWindowSize: 10")


def test_signature_silent_on_plain_code() -> None:
    assert not fires("circuit-breaker", "public Inventory reserve(String sku) { return inventory.lookup(sku); }")


def test_timeout_and_retry_signatures() -> None:
    assert fires("timeout", '@TimeLimiter(name="inv")')
    assert fires("timeout", "await Policy.TimeoutAsync(2).ExecuteAsync(call);")
    assert fires("retry", '@Retry(name="inv")')


def test_unknown_concern_never_fires() -> None:
    assert not fires("not-a-concern", "@CircuitBreaker")
    assert "circuit-breaker" in concerns()


def test_rederive_aliases_fires() -> None:
    assert rederive("circuit-breaker", "@CircuitBreaker") is True
    assert rederive("circuit-breaker", "no breaker here") is False


def test_resiliency_claim_re_derives_via_signature() -> None:
    """The ResiliencyPattern claim now carries a signature, not a keyword needle."""
    claim = extract_claims({"kind": "ResiliencyPattern", "spec": {}, "evidence": [{}]})[0]
    assert claim.signature == "circuit-breaker" and claim.needle is None

    c = GroundingChallenger()
    assert c.adjudicate(claim, "@CircuitBreaker(name=x) public Foo call() {").verdict == "supported"
    assert c.adjudicate(claim, "public Inventory reserve() { return lookup(); }").verdict == "unsupported"
