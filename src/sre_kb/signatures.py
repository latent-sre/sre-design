"""Detection signatures — named, deterministic rules for resilience patterns, shared as the
re-derivation contract (HYBRID-PLAN §6.3 step 2 / §7.4).

A signature answers one question deterministically: *does pattern `<concern>` appear in this
excerpt?* The challenge gate uses it to re-derive a proposed claim ("does signature S fire at
the pointer the LLM proposed?") instead of a bare substring check — the difference between
proving the model quoted its own keyword and proving the pattern is actually there
(`validation/challenge.py` warns about exactly that self-consistency trap).

One library, so the patterns Tier-A (AST) detection keys off and the patterns Tier-B
re-derivation confirms can't drift — detection config becomes data, not code. Tier-A
collectors consuming this directly (parameterizing the AST match by signature data) is the
larger unification step left for Phase 4; today the library is the re-derivation source.
"""

from __future__ import annotations

import re

# concern -> patterns evidencing it across Java/Spring (resilience4j), .NET (Polly), and config.
_SIGNATURES: dict[str, list[re.Pattern]] = {
    "circuit-breaker": [
        re.compile(p, re.I)
        for p in (
            r"@CircuitBreaker\b",                 # resilience4j annotation
            r"\bCircuitBreaker(?:Async)?\s*\(",   # Polly: (Async)CircuitBreaker(...)
            r"\.CircuitBreaker(?:Async)?\b",      # Polly fluent
            r"resilience4j\.circuitbreaker",      # config
        )
    ],
    "fallback": [
        re.compile(p, re.I)
        for p in (
            r"fallbackMethod\s*=",                # resilience4j @CircuitBreaker(fallbackMethod=...)
            r"@Recover\b",                        # spring-retry
            r"\.Fallback(?:Async)?\s*\(",         # Polly
            r"fallback",                          # XxxFallback method-name convention
        )
    ],
    "timeout": [
        re.compile(p, re.I)
        for p in (
            r"@TimeLimiter\b",                    # resilience4j
            r"\bTimeout(?:Async)?\s*\(",          # Polly Timeout/TimeoutAsync
            r"\b(?:connect|read|response)Timeout\b",
            r"resilience4j\.timelimiter",
        )
    ],
    "retry": [
        re.compile(p, re.I)
        for p in (r"@Retry\b", r"\bWaitAndRetry\w*\s*\(", r"\bRetry(?:Async)?\s*\(")
    ],
}


def concerns() -> list[str]:
    """The concerns this library can re-derive."""
    return list(_SIGNATURES)


def fires(concern: str, excerpt: str) -> bool:
    """True iff the signature for `concern` matches `excerpt`. Unknown concern -> False."""
    return any(p.search(excerpt) for p in _SIGNATURES.get(concern, ()))


def rederive(concern: str, excerpt: str) -> bool:
    """The Tier-B re-derivation contract: an LLM proposes (concern, pointer); the engine
    confirms the fact deterministically with the same signature Tier-A would key off. Alias of
    `fires`, named for the call site that matters (HYBRID-PLAN §6.3 step 2)."""
    return fires(concern, excerpt)
