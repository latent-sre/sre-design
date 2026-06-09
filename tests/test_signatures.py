"""§7.4 — the shared signature library + re-derivation. A signature fires on the real pattern
(across Java/Spring and .NET/Polly), not on a bare keyword, and the challenge gate re-derives a
ResiliencyPattern claim by asking "does the signature fire at the cited location?".
"""

from __future__ import annotations

from sre_kb.signatures import concerns, fires, rederive, signature
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


def test_fallback_signature_matches_mechanisms_not_the_bare_word() -> None:
    """§9.5 ⑤: as a refuter for `unguarded-critical-dependency`, the fallback signature must fire on
    a real fallback *mechanism*, never the bare word in a comment/identifier — a false fire there
    silently drops a real gap."""
    assert fires("fallback", '@CircuitBreaker(name="p", fallbackMethod = "charge")')  # resilience4j
    assert fires("fallback", "@Recover")                                              # Spring Retry
    assert fires("fallback", "Policy.Handle<Exception>().FallbackAsync(ct => alt)")   # Polly
    assert fires("fallback", "Decorators.ofSupplier(s).withFallback(t -> alt)")       # resilience4j-vavr
    assert fires("fallback", '@FeignClient(name = "p", fallback = PFallback.class)')  # Spring Cloud Feign
    # These used to false-refute a real gap (the bare-substring bug):
    assert not fires("fallback", "// TODO: add a fallback path here")                 # comment prose
    assert not fires("fallback", 'String fallbackUrl = props.get("url");')            # identifier
    assert not fires("fallback", 'log.warn("no fallback configured");')               # string literal


def test_bulkhead_rate_limit_idempotency_signatures() -> None:
    """N3: the resilience vocabulary now matches resiliency-skills' taxonomy (bulkhead, rate-limit,
    idempotency) — fire on the mechanism across stacks, silent on prose/identifiers."""
    assert fires("bulkhead", '@Bulkhead(name="inv", type = Bulkhead.Type.THREADPOOL)')      # resilience4j
    assert fires("bulkhead", "Policy.BulkheadAsync(maxParallelization: 8);")                # Polly
    assert fires("bulkhead", "resilience4j.thread-pool-bulkhead.instances.inv.coreThreadPoolSize: 4")
    assert fires("rate-limit", '@RateLimiter(name="inv")')                                  # resilience4j
    assert fires("rate-limit", "resilience4j.ratelimiter.instances.inv.limitForPeriod: 10")
    assert fires("rate-limit", "builder.Services.AddRateLimiter(o => { });")                # ASP.NET Core
    assert fires("idempotency", 'headers.set("Idempotency-Key", key);')
    assert fires("idempotency", "@Idempotent public void apply(Command c) {")
    # silent on prose / unrelated identifiers (a false fire here would mislead a re-derivation probe)
    assert not fires("bulkhead", "public Inventory reserve(String sku) { return lookup(sku); }")
    assert not fires("rate-limit", "// consider adding a rate limit here later")
    assert not fires("idempotency", 'log.info("processing order " + id);')
    for c in ("bulkhead", "rate-limit", "idempotency"):
        assert c in concerns()


def test_load_shed_and_backpressure_signatures() -> None:
    """N5: the resilience vocabulary gains load-shed + backpressure — fire on the mechanism across
    stacks (Reactor/RxJava, JDK bounded queues, Go channels, .NET, nginx), silent on prose."""
    assert fires("backpressure", "flux.onBackpressureBuffer(256).subscribe(this::handle);")        # Reactor
    assert fires("backpressure", "source.onBackpressureDrop().observeOn(scheduler)")               # RxJava
    assert fires("backpressure", "private final Queue<Task> q = new ArrayBlockingQueue<>(1000);")  # bounded JDK
    assert fires("backpressure", "var q = new LinkedBlockingQueue<Event>(500);")                   # capacity-bounded
    assert fires("backpressure", "ch := make(chan Job, 128)")                                      # Go buffered channel
    assert fires("backpressure", "const rs = new Readable({ highWaterMark: 16384 });")             # Node stream
    assert fires("load-shed", "if (!semaphore.tryAcquire()) return Response.status(503).build();")  # shed on full
    assert fires("load-shed", "if !sem.TryAcquire(ctx, 1) { return errBusy }")                     # Go semaphore
    assert fires("load-shed", "options.RejectionStatusCode = 503;")                                # ASP.NET limiter
    assert fires("load-shed", "limit_req zone=api burst=20 nodelay;")                              # nginx
    # silent on prose / unbounded forms (a false fire here would silently drop a real gap, §9.5 ⑤)
    assert not fires("backpressure", "// TODO: add backpressure to this stream")
    assert not fires("backpressure", "events := make(chan Job)")          # unbuffered channel: no bound
    assert not fires("backpressure", "queue = new LinkedBlockingQueue<>()")  # unbounded queue
    assert not fires("load-shed", "// we should shed load when overwhelmed")
    assert not fires("load-shed", "public Inventory reserve(String sku) { return lookup(sku); }")
    for c in ("backpressure", "load-shed"):
        assert c in concerns()


def test_dead_letter_signature_matches_dlq_mechanisms() -> None:
    assert "dead-letter" in concerns()
    assert fires("dead-letter", "@RetryableTopic(attempts = \"3\")")           # Spring Kafka
    assert fires("dead-letter", "@DltHandler public void dlt(Order o) {}")
    assert fires("dead-letter", "spring.cloud.stream.kafka.bindings.in.consumer.enableDlq: true")
    assert fires("dead-letter", "  arguments: { x-dead-letter-exchange: dlx }")  # RabbitMQ
    # silent on prose — a false fire would drop a real consumer-without-dlq gap (§9.5 ⑤)
    assert not fires("dead-letter", "// route failures to a dead letter queue eventually")


def test_unknown_concern_never_fires() -> None:
    assert not fires("not-a-concern", "@CircuitBreaker")
    assert "circuit-breaker" in concerns()


def test_rederive_aliases_fires() -> None:
    assert rederive("circuit-breaker", "@CircuitBreaker") is True
    assert rederive("circuit-breaker", "no breaker here") is False


def test_signature_exposes_shared_tier_a_tokens() -> None:
    """One rule, both tiers: the AST tokens the collectors key off live in the same Signature as
    the text patterns Tier-B re-derives with (HYBRID-PLAN §7.4)."""
    cb = signature("circuit-breaker")
    assert cb is not None
    assert "@CircuitBreaker" in cb.annotations    # the Java AST collector keys off this
    assert "CircuitBreaker" in cb.call_tokens     # the .NET AST collector keys off this
    assert cb.fires("@CircuitBreaker(name=x)")    # and the text patterns re-derive the same tokens
    assert cb.fires("Policy.Handle<Exception>().CircuitBreakerAsync(5, t)")


def test_resiliency_claim_re_derives_via_signature() -> None:
    """The ResiliencyPattern claim now carries a signature, not a keyword needle."""
    claim = extract_claims({"kind": "ResiliencyPattern", "spec": {}, "evidence": [{}]})[0]
    assert claim.signature == "circuit-breaker" and claim.needle is None

    c = GroundingChallenger()
    assert c.adjudicate(claim, "@CircuitBreaker(name=x) public Foo call() {").verdict == "supported"
    assert c.adjudicate(claim, "public Inventory reserve() { return lookup(); }").verdict == "unsupported"


def test_timeout_signature_does_not_fire_on_disabled_timeout() -> None:
    """#H2: `timeout` is a refuting concern (a fire silently drops a gap), so a *disabled* timeout
    must NOT fire — else a real missing-timeout risk is hidden. Enabled values still fire."""
    assert not fires("timeout", "timeout = 0")        # disabled
    assert not fires("timeout", "timeout = None")     # disabled (Python)
    assert not fires("timeout", "self.timeout = null")
    assert fires("timeout", "timeout=30")             # real values still detected
    assert fires("timeout", "timeout = 0.5")
    assert fires("timeout", "self.timeout = httpx.Timeout(5.0)")
