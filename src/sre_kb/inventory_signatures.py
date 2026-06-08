"""Declarative inventory signatures — data-driven classification for the P2 inventory roll-up
(HYBRID-PLAN §9.7 N5).

The resilience `signatures` library names *patterns*; this names the *inventory* the engine rolls up:
which datastore engine / message broker a dependency name denotes, and which language/runtime/build
tool a repo's manifest files imply. Like `signatures`, detection is **data, not code** — widening
coverage to a new stack (Node, Go, …) or a new engine is a row added here, not a branch added to
`synth/inventory.py`. That is the breadth path: extend a table, deterministically and without drift.

Three classification families, each a frozen, ordered catalog with first-match-wins lookup:
  - DataStoreSig — a binding/dependency name -> a canonical datastore `engine` (postgres, redis, …);
  - BrokerSig    — a binding/dependency name -> a canonical message `kind` (kafka, rabbitmq, …);
  - StackSig     — the manifest files present in a repo -> (language, runtime, buildTool).

`hints` are matched as case-insensitive substrings of the name; order matters, so specific engines
precede the generic `sql`/`db` fallback (`mysql` must not resolve to the generic `sql`). Stacks are
ordered most-specific / least-incidental first, so a polyglot repo resolves to one deterministic
primary stack (a Go service with a stray `package.json` is Go, not Node).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch


@dataclass(frozen=True)
class DataStoreSig:
    engine: str                 # canonical engine name, e.g. "postgres"
    hints: tuple[str, ...]      # name substrings that denote it, e.g. ("postgres", "pgsql")


@dataclass(frozen=True)
class BrokerSig:
    kind: str                   # canonical broker kind, e.g. "kafka"
    hints: tuple[str, ...]


@dataclass(frozen=True)
class StackSig:
    language: str               # java | python | javascript | typescript | go | csharp
    runtime: str                # jvm | cpython | node | go | dotnet
    build_tool: str             # maven | gradle | pip | poetry | npm | gomod | dotnet
    manifests: tuple[str, ...]  # filename globs that identify the stack, e.g. ("go.mod",), ("*.csproj",)


# Specific engines first; the generic `sql`/`db` fallbacks last so they only catch what no specific
# engine claimed (`mongodb` contains "db" but resolves to mongodb, not the generic fallback).
_DATASTORES: tuple[DataStoreSig, ...] = (
    DataStoreSig("postgres", ("postgres", "postgresql", "pgsql", "pgbouncer")),
    DataStoreSig("cockroach", ("cockroach", "crdb")),
    DataStoreSig("mysql", ("mysql", "mariadb", "aurora-mysql")),
    DataStoreSig("oracle", ("oracle", "ojdbc")),
    DataStoreSig("mssql", ("mssql", "sqlserver", "sql-server")),
    DataStoreSig("db2", ("db2",)),
    DataStoreSig("mongodb", ("mongodb", "mongo", "mongoose", "documentdb")),
    DataStoreSig("redis", ("redis", "ioredis", "go-redis", "lettuce", "jedis", "elasticache", "valkey")),
    DataStoreSig("cassandra", ("cassandra", "scylla", "datastax")),
    DataStoreSig("dynamodb", ("dynamodb", "dynamo")),
    DataStoreSig("elasticsearch", ("elasticsearch", "opensearch")),
    DataStoreSig("couchbase", ("couchbase",)),
    DataStoreSig("neo4j", ("neo4j",)),
    DataStoreSig("sqlite", ("sqlite",)),
    DataStoreSig("spanner", ("spanner",)),
    DataStoreSig("bigtable", ("bigtable",)),
    # Generic last-resort: a JDBC/SQL/db-shaped name no specific engine claimed (parity with the
    # historical `("sql", "db")` hints, kept broad on purpose for service-binding names).
    DataStoreSig("sql", ("jdbc", "sql", "rdbms")),
    DataStoreSig("database", ("db",)),
)

_BROKERS: tuple[BrokerSig, ...] = (
    BrokerSig("kafka", ("kafka", "kafkajs", "sarama", "confluent", "msk")),
    BrokerSig("rabbitmq", ("rabbit", "rabbitmq", "amqp", "amqplib")),
    BrokerSig("activemq", ("activemq", "artemis")),
    BrokerSig("servicebus", ("servicebus", "azure-servicebus")),
    BrokerSig("eventhub", ("eventhub", "event-hub")),
    BrokerSig("pulsar", ("pulsar",)),
    BrokerSig("nats", ("nats",)),
    BrokerSig("sqs", ("sqs",)),
    BrokerSig("sns", ("sns",)),
    BrokerSig("pubsub", ("pubsub",)),
    BrokerSig("jms", ("jms",)),
    BrokerSig("ibm-mq", ("ibmmq", "ibm-mq")),
    # Generic last-resort message-queue (parity with the historical `mq` hint).
    BrokerSig("message-queue", ("mq",)),
)

# Most-specific / least-incidental first: `tsconfig.json` (TypeScript) before bare `package.json`
# (JavaScript); go before node so a Go service's tooling `package.json` doesn't mask it.
_STACKS: tuple[StackSig, ...] = (
    StackSig("java", "jvm", "maven", ("pom.xml",)),
    StackSig("java", "jvm", "gradle", ("build.gradle", "build.gradle.kts", "settings.gradle")),
    StackSig("csharp", "dotnet", "dotnet", ("*.csproj", "*.sln")),
    StackSig("python", "cpython", "poetry", ("pyproject.toml",)),
    StackSig("python", "cpython", "pip", ("requirements.txt", "requirements-*.txt", "setup.py")),
    StackSig("go", "go", "gomod", ("go.mod",)),
    StackSig("typescript", "node", "npm", ("tsconfig.json",)),
    StackSig("javascript", "node", "npm", ("package.json",)),
)


def datastore_engine(name: str) -> str | None:
    """Canonical datastore engine for a binding/dependency name, or None if it isn't a datastore."""
    low = name.lower()
    return next((s.engine for s in _DATASTORES if any(h in low for h in s.hints)), None)


def broker_kind(name: str) -> str | None:
    """Canonical message-broker kind for a binding/dependency name, or None if it isn't a broker."""
    low = name.lower()
    return next((s.kind for s in _BROKERS if any(h in low for h in s.hints)), None)


def is_datastore(name: str) -> bool:
    return datastore_engine(name) is not None


def is_broker(name: str) -> bool:
    return broker_kind(name) is not None


def is_manifest_of(sig: StackSig, name: str) -> bool:
    """True iff a present filename matches one of the stack's manifest globs (case-insensitive)."""
    low = name.lower()
    return any(fnmatch(low, pat) for pat in sig.manifests)


def stack_for_manifests(names: Iterable[str]) -> StackSig | None:
    """The primary tech stack implied by the manifest filenames present in a repo, or None. First
    matching catalog entry wins, so the ordering is the polyglot tie-break."""
    present = [n.lower() for n in names]
    return next((s for s in _STACKS if any(is_manifest_of(s, n) for n in present)), None)


def all_manifests() -> tuple[str, ...]:
    """Every manifest glob across all stacks (de-duplicated) — the set to scan a repo for."""
    return tuple(dict.fromkeys(m for s in _STACKS for m in s.manifests))


def engines() -> list[str]:
    return [s.engine for s in _DATASTORES]


def broker_kinds() -> list[str]:
    return [s.kind for s in _BROKERS]


def stacks() -> tuple[StackSig, ...]:
    return _STACKS
