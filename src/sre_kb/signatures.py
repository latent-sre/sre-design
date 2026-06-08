"""Detection signatures — named, deterministic rules for resilience patterns, shared by both
trust tiers (HYBRID-PLAN §6.3 step 2 / §7.4).

One concern, one `Signature`, three projections of the same rule:
  - `annotations` — Java/Spring annotation keys the Tier-A AST collector keys off;
  - `call_tokens` — substrings in a .NET/Polly call/field name the Tier-A AST collector keys off;
  - `patterns`    — text regex used for Tier-B *re-derivation* ("does the signature fire at the
                    LLM-proposed pointer?") and as the grounding check in `validation/challenge.py`.

Because Tier-A detection and Tier-B re-derivation read the same library, the two can't drift —
detection config is data, not code, and adding a stack means extending the data here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Signature:
    concern: str
    annotations: tuple[str, ...] = ()     # Tier-A (Java AST): annotation keys, e.g. "@CircuitBreaker"
    call_tokens: tuple[str, ...] = ()     # Tier-A (.NET AST): call/field-name substrings, e.g. "CircuitBreaker"
    patterns: tuple[re.Pattern, ...] = ()  # Tier-B re-derivation / grounding: text regex

    def fires(self, excerpt: str) -> bool:
        return any(p.search(excerpt) for p in self.patterns)


def _p(*pats: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.I) for p in pats)


_SIGNATURES: dict[str, Signature] = {
    s.concern: s
    for s in (
        Signature(
            "circuit-breaker",
            annotations=("@CircuitBreaker",),
            call_tokens=("CircuitBreaker",),
            patterns=_p(
                r"@CircuitBreaker\b",                 # resilience4j annotation
                r"\bCircuitBreaker(?:Async)?\s*\(",   # Polly: (Async)CircuitBreaker(...)
                r"\.CircuitBreaker(?:Async)?\b",      # Polly fluent
                r"resilience4j\.circuitbreaker",      # config
            ),
        ),
        Signature(
            "fallback",
            annotations=("@Recover",),
            call_tokens=("Fallback",),
            # Match a fallback *mechanism*, never the bare word: a bare `fallback` substring fired on
            # the word in a comment / string / identifier (e.g. `fallbackUrl`), which — as a refuter
            # for `unguarded-critical-dependency` — silently dropped real gaps (HYBRID-PLAN §9.5 ⑤).
            patterns=_p(
                r"\bfallback(?:Method|Factory)?\s*=",   # resilience4j fallbackMethod=; Spring Cloud Feign fallback=/fallbackFactory=
                r"@Recover\b",                          # Spring Retry recovery method
                r"\.(?:with)?Fallback(?:Async)?\s*\(",  # Polly .Fallback(/.FallbackAsync(; resilience4j-vavr .withFallback(
            ),
        ),
        Signature(
            "timeout",
            annotations=("@TimeLimiter",),
            call_tokens=("Timeout",),
            patterns=_p(
                r"@TimeLimiter\b",
                r"\bTimeout(?:Async)?\s*\(",
                r"\b(?:connect|read|response)Timeout\b",
                r"resilience4j\.timelimiter",
                r"\btimeout\s*=",  # Python httpx/requests kwarg; also Polly/Java fluent `Timeout =`
            ),
        ),
        Signature(
            "retry",
            annotations=("@Retry",),
            call_tokens=("Retry", "WaitAndRetry"),
            patterns=_p(r"@Retry\b", r"\bWaitAndRetry\w*\s*\(", r"\bRetry(?:Async)?\s*\("),
        ),
        Signature(
            "bulkhead",  # concurrency isolation — resilience4j @Bulkhead/ThreadPoolBulkhead, Polly Bulkhead
            annotations=("@Bulkhead",),
            call_tokens=("Bulkhead",),
            patterns=_p(
                r"@Bulkhead\b",
                r"\bThreadPoolBulkhead\b",
                r"\bBulkhead(?:Async)?\s*\(",          # Polly: Bulkhead(/BulkheadAsync(
                r"\.Bulkhead(?:Async)?\b",             # Polly fluent
                r"resilience4j\.(?:thread-pool-)?bulkhead",
            ),
        ),
        Signature(
            "rate-limit",  # request rate limiting — resilience4j @RateLimiter, Polly/ASP.NET limiters
            annotations=("@RateLimiter",),
            call_tokens=("RateLimit", "RateLimiter"),
            patterns=_p(
                r"@RateLimiter\b",
                r"resilience4j\.ratelimiter",
                r"\bRateLimiter\s*\(",                 # Bucket4j/Guava RateLimiter(...)
                r"\.RateLimit(?:Async)?\b",            # Polly fluent .RateLimit(
                r"\bAddRateLimiter\b",                 # ASP.NET Core rate-limiting middleware
            ),
        ),
        Signature(
            "idempotency",  # replay/de-dup safety on a write or consumer (heuristic — names, not one annotation)
            annotations=("@Idempotent",),
            call_tokens=("Idempoten",),
            patterns=_p(
                r"\bidempotenc(?:y|e)[-_]?key\b",      # Idempotency-Key header / idempotencyKey field
                r"@Idempotent\b",
                r"\bIdempotencyKey\b",
                r"\bdedupe[-_]?key\b",
            ),
        ),
        Signature(
            "scheduled",  # a recurring/background job — Spring @Scheduled, Quartz, or Python schedulers
            annotations=("@Scheduled",),
            call_tokens=("RecurringJob", "ScheduleJob"),
            patterns=_p(
                r"@Scheduled\b", r"@DisallowConcurrentExecution\b",          # Java/Spring/Quartz
                r"@(?:shared_task|periodic_task|task)\b", r"@app\.on_event\b",  # Celery / FastAPI
                r"@\w*scheduler\.scheduled_job\b", r"\bBackgroundScheduler\b",  # APScheduler
                r"@repeat_every\b",                                          # fastapi-utils
            ),
        ),
        Signature(
            "backpressure",  # bounding an unbounded producer/queue — reactive operators or a bounded buffer
            # No annotation/call-token: no AST collector keys off these yet. The patterns ride
            # re-derivation, challenge grounding, and the gap-finder's judgment refuter. They fire on a
            # mechanism, never a bare word — a false fire here silently drops a real gap (§9.5 ⑤).
            patterns=_p(
                r"\.onBackpressure(?:Buffer|Drop|Latest|Error)\s*\(",  # Reactor / RxJava operators
                r"\.limitRate\s*\(",                                   # Reactor demand cap
                r"\bBackpressureStrategy\.",                           # RxJava strategy enum
                r"\bOverflowStrategy\.",                               # Akka/Pekko stream buffer strategy
                r"\bnew\s+ArrayBlockingQueue\b",                       # always-bounded JDK queue
                r"\bnew\s+LinkedBlocking(?:Queue|Deque)\s*(?:<[^>]*>)?\s*\(\s*\w",  # capacity-bounded JDK queue
                r"\bChannel\.CreateBounded\b", r"\bBoundedChannelOptions\b",        # .NET bounded channel
                r"\bmake\s*\(\s*chan\b[^,)]*,\s*\w",                   # Go buffered (bounded) channel
                r"\bhighWaterMark\s*[:=]",                             # Node stream backpressure knob
            ),
        ),
        Signature(
            "load-shed",  # rejecting/dropping excess load when overloaded (vs. queueing it unboundedly)
            patterns=_p(
                r"\btryAcquire\s*\(",            # Semaphore non-blocking/timed acquire (Java/Go/.NET) -> shed on full
                r"\bConcurrencyLimit(?:er)?\b",  # Netflix concurrency-limits / adaptive concurrency limiter
                r"\bRejectionStatusCode\b",      # ASP.NET Core / Polly rate-limiter rejection (sheds excess)
                r"\blimit_(?:req|conn)\b",       # nginx / envoy load-shedding directives
            ),
        ),
    )
}


def concerns() -> list[str]:
    """The concerns this library can detect / re-derive."""
    return list(_SIGNATURES)


def signature(concern: str) -> Signature | None:
    """The full signature for a concern (Tier-A tokens + Tier-B patterns), or None if unknown."""
    return _SIGNATURES.get(concern)


def fires(concern: str, excerpt: str) -> bool:
    """True iff the signature for `concern` matches `excerpt`. Unknown concern -> False."""
    sig = _SIGNATURES.get(concern)
    return sig.fires(excerpt) if sig else False


def rederive(concern: str, excerpt: str) -> bool:
    """The Tier-B re-derivation contract: an LLM proposes (concern, pointer); the engine confirms
    the fact deterministically with the same signature Tier-A keys off (HYBRID-PLAN §6.3 step 2)."""
    return fires(concern, excerpt)
