"""Messaging collector (S3 `map-messaging`, Tier-A): consumer-side async resilience.

The publisher side already emits `message.egress`; this reads the *consumer* side — the
`@KafkaListener` / `@RabbitListener` / `@SqsListener` / `@JmsListener` handlers — and the resilience
mechanisms wired around them: a dead-letter route (`@RetryableTopic` / `@DltHandler` /
`DeadLetterPublishingRecoverer` / binder DLQ config), retry, and an idempotency guard. Detection rides
the shared `signatures` library (`dead-letter`, `idempotency`), so Tier-A detection and the Tier-B
`map-messaging` refutation can't drift.

Two outputs:
  - `collect(ctx)` emits one `message.consumer` fact per handler (the descriptive `Messaging`
    artifact), cited to the listener annotation.
  - `collect_gaps(ctx, fs)` emits deterministic Tier-A `resiliency.gap` facts — `consumer-without-dlq`
    (a poison pill blocks the partition) and `non-idempotent-consumer` (a redelivery double-processes)
    — for consumers missing the mechanism in scope. These ride the same `scaffold_gap` path as the
    resilience4j parameter-completeness gaps (R5): `source_tier=ast`, so they can verify.

Ordering/partition safety, poison-pill *adequacy*, and saga compensation are judgment calls with no
deterministic ground truth — they route to the Tier-B `map-messaging` skill, not here.
"""

from __future__ import annotations

from sre_kb.collectors.base import ScanContext
from sre_kb.models.facts import Fact, FactSet, Symbol
from sre_kb.signatures import fires
from sre_kb.util import fqn

# Listener annotation -> (broker, the annotation keys that name the channel, most-specific first).
# `""` is the positional argument (`@SqsListener("queue")`).
_LISTENERS = {
    "@KafkaListener": ("kafka", ("topics", "id")),
    "@RabbitListener": ("rabbit", ("queues", "")),
    "@SqsListener": ("sqs", ("value", "")),
    "@JmsListener": ("jms", ("destination", "")),
}

_CONFIG_GLOBS = ("application.yml", "application.yaml", "application-*.yml",
                 "application*.properties", "bootstrap.yml")


def _channel(args: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        val = args.get(key)
        if val:
            return val
    return "unknown"


def _config_dlq(ctx: ScanContext) -> bool:
    """A binder-level dead-letter route declared in config (Spring Cloud Stream `enableDlq`, RabbitMQ
    `x-dead-letter-*`). Read from the config *files*, not the consumer's type text — a code comment
    mentioning `@RetryableTopic` must not count as a DLQ and suppress a real gap (§9.5 ⑤)."""
    return any(fires("dead-letter", ctx.read_text(ctx.rel(p))) for p in ctx.files(*_CONFIG_GLOBS))


def _dlq_mechanism(t, config_dlq: bool) -> str | None:
    """The dead-letter mechanism for this consumer, or None. Annotation signals are consumer-scoped
    and read from the AST (robust); a binder DLQ in config is the catch-all."""
    anns = {a for m in t.methods for a in m.annotations}
    if "@RetryableTopic" in anns:
        return "retryable-topic"
    if "@DltHandler" in anns:
        return "dlt-handler"
    if config_dlq:
        return "config"
    return None


def _consumers(ctx: ScanContext):
    """Yield a `message.consumer` fact for every messaging consumer handler."""
    config_dlq = _config_dlq(ctx)
    for path in ctx.files("*.java"):
        rel = ctx.rel(path)
        module = ctx.module(rel, "java")
        ns = module.namespace
        for t in module.types:
            type_text = "".join(ctx.read_lines(rel)[t.start - 1 : t.end])
            dl_mech = _dlq_mechanism(t, config_dlq)
            idempotent = fires("idempotency", type_text)
            for m in t.methods:
                ann = next((a for a in _LISTENERS if a in m.annotations), None)
                if ann is None:
                    continue
                broker, keys = _LISTENERS[ann]
                channel = _channel(m.annotations[ann], keys)
                retry = "@RetryableTopic" in m.annotations
                handler = fqn(ns, t.name, m.name)
                yield Fact(
                    "message.consumer",
                    {
                        "channel": channel,
                        "broker": broker,
                        "handler": handler,
                        "deadLetter": dl_mech is not None,
                        "deadLetterMechanism": dl_mech,
                        "retry": retry,
                        "idempotentConsumer": idempotent,
                    },
                    ctx.evidence(rel, m.start, m.name_line, "java_spring.messaging"),
                    Symbol(handler, "method"),
                )


def collect(ctx: ScanContext) -> list[Fact]:
    return list(_consumers(ctx))


# (resilience attr that, when False, is a gap) -> (category, severity, the risk it leaves open).
_GAP_SPECS = (
    ("deadLetter", "consumer-without-dlq", "high",
     "no dead-letter route, so a poison-pill message blocks the partition and is retried forever"),
    ("idempotentConsumer", "non-idempotent-consumer", "medium",
     "no idempotency guard, so an at-least-once redelivery double-processes the message"),
)


def collect_gaps(ctx: ScanContext, fs: FactSet) -> list[Fact]:
    """Deterministic Tier-A consumer-resilience gaps, derived from the `message.consumer` facts.
    Mirrors `resiliency_params` (R5): byte-grounded absence the engine asserts itself, no LLM. The
    DLQ gap records the config files it searched too, so the absence is an honest negative."""
    config_checked = [ctx.rel(p) for p in ctx.files(*_CONFIG_GLOBS)]
    gaps: list[Fact] = []
    for c in fs.of("message.consumer"):
        a = c.attrs
        for attr, category, severity, risk in _GAP_SPECS:
            if a.get(attr):
                continue
            checked = [c.evidence.path] + (config_checked if attr == "deadLetter" else [])
            gaps.append(Fact(
                "resiliency.gap",
                {
                    "category": category,
                    "target": a["channel"],
                    "severity": severity,
                    "rationale": f"consumer {a['handler']} on '{a['channel']}' has {risk}.",
                    "rederivation": "consumer-resilience",
                    "checked": checked,
                },
                c.evidence,
                Symbol(a["handler"], "method"),
            ))
    return gaps
