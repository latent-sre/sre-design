"""Static operational signals for code, shell, SQL, YAML, and Dockerfiles.

Signals are discovery aids for an SRE or runbook author. They are deliberately labeled
``STATIC_EXTRACTED``: an API-shaped call or deployment key is not proof of a runtime dependency,
production topology, or a safe incident command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

from sre_kb.parsing.code_model import syntax_matches
from sre_kb.parsing.structural import StructuralRule, find_structural_matches

_AST_LANGUAGES = frozenset(
    {"bash", "csharp", "go", "java", "javascript", "python", "tsx", "typescript"}
)
_MEMBER_LANGUAGES = frozenset({"csharp", "java", "javascript", "python", "tsx", "typescript"})
_JS_LANGUAGES = frozenset({"javascript", "tsx", "typescript"})

_MEMBER_CALL_RULE = StructuralRule(
    rule_id="operational.member-call",
    category="call",
    summary="member call expression",
    languages=_MEMBER_LANGUAGES,
    configs=({"pattern": "$RECEIVER.$METHOD($$$ARGS)"},),
    captures=("METHOD", "RECEIVER"),
)
_GO_CALL_RULE = StructuralRule(
    rule_id="operational.go-call",
    category="call",
    summary="Go selector call expression",
    languages=frozenset({"go"}),
    configs=(
        {
            "pattern": {
                "context": "package main\nfunc f() { $RECEIVER.$METHOD($$$ARGS) }",
                "selector": "call_expression",
            }
        },
    ),
    captures=("METHOD", "RECEIVER"),
)
_BASH_COMMAND_RULE = StructuralRule(
    rule_id="operational.bash-command",
    category="call",
    summary="shell command",
    languages=frozenset({"bash"}),
    configs=({"pattern": "$COMMAND $$$ARGS"},),
    captures=("COMMAND",),
)
_FUNCTION_RULE = StructuralRule(
    rule_id="operational.function-call",
    category="call",
    summary="function call",
    languages=_JS_LANGUAGES,
    configs=({"pattern": "$FUNCTION($$$ARGS)"},),
    captures=("FUNCTION",),
)
_JS_ENV_RULE = StructuralRule(
    rule_id="operational.environment-property",
    category="config.environment",
    summary="reads a process environment value",
    languages=_JS_LANGUAGES,
    configs=({"pattern": "$PROCESS.env.$NAME"},),
    captures=("NAME", "PROCESS"),
)

_PROCESS_RECEIVERS = {"child_process", "exec", "os", "process", "runtime", "subprocess"}
_PROCESS_METHODS = {
    "command",
    "exec",
    "execfile",
    "popen",
    "run",
    "spawn",
    "start",
    "system",
}
_NETWORK_RECEIVERS = {
    "aiohttp",
    "axios",
    "fetch",
    "http",
    "httpclient",
    "httpx",
    "requests",
    "restclient",
    "resttemplate",
    "urllib",
    "urllib3",
    "webclient",
}
_NETWORK_METHODS = {
    "delete",
    "do",
    "exchange",
    "fetch",
    "get",
    "getasync",
    "head",
    "patch",
    "post",
    "postasync",
    "put",
    "request",
    "sendasync",
}
_DATASTORE_RECEIVER_PARTS = {
    "connection",
    "context",
    "cursor",
    "database",
    "db",
    "repo",
    "repository",
    "session",
}
_DATASTORE_METHODS = {
    "commit",
    "delete",
    "execute",
    "executemany",
    "find",
    "insert",
    "query",
    "rollback",
    "save",
    "update",
}
_MESSAGE_RECEIVER_PARTS = {
    "broker",
    "bus",
    "event",
    "kafka",
    "producer",
    "publisher",
    "queue",
    "topic",
}
_MESSAGE_METHODS = {"emit", "produce", "publish", "send"}
_ENV_METHODS = {
    "environ",
    "getenv",
    "getenvironmentvariable",
    "getproperty",
    "lookupenv",
}
_LISTEN_METHODS = {"bind", "listen", "run", "serve", "startasync"}
_OBSERVABILITY_METHODS = {
    "counter",
    "critical",
    "debug",
    "error",
    "fatal",
    "histogram",
    "info",
    "log",
    "trace",
    "warning",
}
_SERVICE_COMMANDS = {"cf", "docker", "kubectl", "podman", "service", "systemctl"}
_NETWORK_COMMANDS = {"curl", "nc", "netcat", "wget"}
_DATASTORE_COMMANDS = {"mongosh", "mysql", "psql", "redis-cli", "sqlcmd"}

_YAML_KEYS = {
    "depends_on": ("deployment.dependency", "declares a deployment dependency"),
    "healthcheck": ("deployment.healthcheck", "declares a container health check"),
    "image": ("deployment.image", "declares a deployable image"),
    "livenessprobe": ("deployment.healthcheck", "declares a liveness probe"),
    "ports": ("deployment.port", "declares an exposed or mapped port"),
    "readinessprobe": ("deployment.healthcheck", "declares a readiness probe"),
    "replicas": ("deployment.scale", "declares a replica count"),
    "resources": ("deployment.resources", "declares deployment resource controls"),
    "restart": ("deployment.restart-policy", "declares a restart policy"),
}
_SQL_SCHEMA_NODES = {"alter_table", "create_table", "drop_table"}
_SQL_MUTATION_NODES = {"delete", "insert", "update"}


@dataclass(frozen=True)
class OperationalSignal:
    category: str
    summary: str
    start_line: int
    end_line: int
    text: str
    evidence_class: str = "STATIC_EXTRACTED"
    annotations: dict[str, str] | None = None


@dataclass(frozen=True)
class DockerfileInstruction:
    instruction: str
    arguments: str
    start_line: int
    end_line: int


def language_for_path(path: str | PurePath) -> str | None:
    value = PurePath(path)
    name = value.name.lower()
    if name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile"):
        return "dockerfile"
    return {
        ".bash": "bash",
        ".cs": "csharp",
        ".go": "go",
        ".java": "java",
        ".js": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".py": "python",
        ".sh": "bash",
        ".sql": "sql",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(value.suffix.lower())


def find_operational_signals(
    language: str,
    text: str,
    *,
    max_signals: int = 200,
) -> list[OperationalSignal]:
    normalized = language.lower()
    if normalized == "dockerfile":
        signals = _dockerfile_signals(text)
    elif normalized == "sql":
        signals = _sql_signals(text)
    elif normalized == "yaml":
        signals = _yaml_signals(text)
    elif normalized in _AST_LANGUAGES:
        signals = _ast_signals(normalized, text, max_signals=max_signals)
    else:
        return []
    dedup = {(item.category, item.start_line, item.end_line, item.text): item for item in signals}
    return sorted(
        dedup.values(),
        key=lambda item: (item.start_line, item.end_line, item.category, item.text),
    )[:max_signals]


def _ast_signals(language: str, text: str, *, max_signals: int) -> list[OperationalSignal]:
    matches = find_structural_matches(
        text,
        language,
        [
            _MEMBER_CALL_RULE,
            _GO_CALL_RULE,
            _BASH_COMMAND_RULE,
            _FUNCTION_RULE,
            _JS_ENV_RULE,
        ],
        max_matches=max_signals * 4,
    )
    signals: list[OperationalSignal] = []
    for match in matches:
        if match.rule_id == _JS_ENV_RULE.rule_id:
            process = _capture(match.captures, "PROCESS").lower()
            if process == "process":
                signals.append(
                    _signal(
                        match,
                        "config.environment",
                        "reads a process environment value",
                    )
                )
            continue
        if match.rule_id == _FUNCTION_RULE.rule_id:
            function = _capture(match.captures, "FUNCTION").lower()
            if function == "fetch":
                signals.append(_signal(match, "network.client", "calls an outbound HTTP API"))
            continue
        if language == "bash":
            command = PurePath(_capture(match.captures, "COMMAND")).name.lower()
            if command in _SERVICE_COMMANDS:
                signals.append(_signal(match, "service.control", "invokes a service control tool"))
            elif command in _NETWORK_COMMANDS:
                signals.append(_signal(match, "network.client", "invokes a network client"))
            elif command in _DATASTORE_COMMANDS:
                signals.append(_signal(match, "database.client", "invokes a datastore client"))
            continue

        receiver = _capture(match.captures, "RECEIVER")
        method = _capture(match.captures, "METHOD")
        method_lower = method.lower()
        annotations = {"receiver": receiver, "method": method}
        if method_lower in _PROCESS_METHODS and (
            _receiver_has(receiver, _PROCESS_RECEIVERS)
        ):
            signals.append(
                _signal(match, "process.exec", "starts an operating-system process", annotations)
            )
        elif method_lower in _NETWORK_METHODS and (
            _receiver_has(receiver, _NETWORK_RECEIVERS | {"client"})
        ):
            signals.append(
                _signal(match, "network.client", "calls an outbound network API", annotations)
            )
        elif method_lower in _ENV_METHODS and _receiver_has(
            receiver, {"environment", "os", "system"}
        ):
            signals.append(
                _signal(
                    match,
                    "config.environment",
                    "reads process or system configuration",
                    annotations,
                )
            )
        elif method_lower in _DATASTORE_METHODS and _receiver_has(
            receiver, _DATASTORE_RECEIVER_PARTS
        ):
            signals.append(
                _signal(match, "database.client", "calls a datastore-shaped API", annotations)
            )
        elif method_lower in _MESSAGE_METHODS and _receiver_has(
            receiver, _MESSAGE_RECEIVER_PARTS
        ):
            signals.append(
                _signal(match, "messaging.client", "calls a messaging-shaped API", annotations)
            )
        elif method_lower in _LISTEN_METHODS and _receiver_has(
            receiver, {"app", "host", "server"}
        ):
            signals.append(
                _signal(
                    match, "service.listener", "starts or binds a service listener", annotations
                )
            )
        elif method_lower in _OBSERVABILITY_METHODS and _receiver_has(
            receiver, {"log", "metric", "trace", "telemetry"}
        ):
            signals.append(
                _signal(
                    match,
                    "observability.emit",
                    "emits an observability-shaped signal",
                    annotations,
                )
            )
    return signals


def _receiver_has(receiver: str, expected: set[str]) -> bool:
    """Match receiver words without substring false positives such as ``catalog`` -> ``log``."""
    forms: set[str] = set()
    for segment in re.split(r"[^A-Za-z0-9_]+", receiver):
        if not segment:
            continue
        forms.add(segment.lower())
        forms.add(re.sub(r"[^a-z0-9]", "", segment.lower()))
        forms.update(
            part.lower()
            for part in re.findall(
                r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+",
                segment,
            )
        )
    expected_forms = {
        form
        for value in expected
        for form in (value.lower(), re.sub(r"[^a-z0-9]", "", value.lower()))
    }
    return not forms.isdisjoint(expected_forms)


def _capture(captures: dict[str, tuple[str, ...]], name: str) -> str:
    values = captures.get(name, ())
    return values[0] if values else ""


def _signal(match, category: str, summary: str, annotations=None) -> OperationalSignal:
    return OperationalSignal(
        category=category,
        summary=summary,
        start_line=match.start_line,
        end_line=match.end_line,
        text=match.text,
        annotations=annotations,
    )


def _sql_signals(text: str) -> list[OperationalSignal]:
    query = """
    [
      (alter_table)
      (create_table)
      (drop_table)
      (delete)
      (insert)
      (update)
    ] @operation
    """
    signals: list[OperationalSignal] = []
    for match in syntax_matches("sql", text, query):
        for capture in match.captures.get("operation", ()):
            if capture.node_kind in _SQL_SCHEMA_NODES:
                category, summary = (
                    "database.schema-change",
                    "declares a database schema change",
                )
            elif capture.node_kind in _SQL_MUTATION_NODES:
                category, summary = (
                    "database.mutation",
                    "declares a database data mutation",
                )
            else:
                continue
            signals.append(
                OperationalSignal(
                    category=category,
                    summary=summary,
                    start_line=capture.start_line,
                    end_line=capture.end_line,
                    text=capture.text,
                    annotations={"nodeKind": capture.node_kind},
                )
            )
    return signals


def _yaml_signals(text: str) -> list[OperationalSignal]:
    query = "(block_mapping_pair key: (flow_node) @key value: (_) @value)"
    signals: list[OperationalSignal] = []
    for match in syntax_matches("yaml", text, query):
        keys = match.captures.get("key", ())
        values = match.captures.get("value", ())
        if not keys:
            continue
        key = keys[0]
        normalized = key.text.strip("\"'").lower()
        classified = _YAML_KEYS.get(normalized)
        if classified is None:
            continue
        value = values[0] if values else key
        category, summary = classified
        signals.append(
            OperationalSignal(
                category=category,
                summary=summary,
                start_line=key.start_line,
                end_line=value.end_line,
                text=f"{key.text}: {value.text}".rstrip(),
                annotations={"key": key.text},
            )
        )
    return signals


def parse_dockerfile(text: str) -> list[DockerfileInstruction]:
    """Parse Dockerfile instruction records, including backslash continuations.

    This narrow parser is used because the MIT Python Dockerfile grammar does not publish a Windows
    wheel. It deliberately extracts instructions only; it does not emulate Docker's build parser or
    run Docker.
    """
    instructions: list[DockerfileInstruction] = []
    pending_name: str | None = None
    pending_parts: list[str] = []
    pending_start = 0
    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if pending_name is None:
            if not stripped or stripped.startswith("#"):
                continue
            match = re.match(r"^([A-Za-z]+)(?:\s+(.*))?$", stripped)
            if match is None:
                continue
            pending_name = match.group(1).upper()
            pending_parts = [match.group(2) or ""]
            pending_start = line_number
        else:
            pending_parts.append(stripped)

        continued = bool(pending_parts[-1].rstrip().endswith("\\"))
        if continued:
            pending_parts[-1] = pending_parts[-1].rstrip()[:-1].rstrip()
            continue
        arguments = " ".join(part.strip() for part in pending_parts if part.strip())
        instructions.append(
            DockerfileInstruction(
                pending_name,
                arguments,
                pending_start,
                line_number,
            )
        )
        pending_name = None
        pending_parts = []
    if pending_name is not None:
        instructions.append(
            DockerfileInstruction(
                pending_name,
                " ".join(part.strip() for part in pending_parts if part.strip()),
                pending_start,
                max(pending_start, len(text.splitlines())),
            )
        )
    return instructions


def _dockerfile_signals(text: str) -> list[OperationalSignal]:
    categories = {
        "EXPOSE": ("deployment.port", "declares an exposed container port"),
        "FROM": ("deployment.base-image", "declares a container base image"),
        "HEALTHCHECK": ("deployment.healthcheck", "declares a container health check"),
        "USER": ("deployment.user", "declares the container runtime user"),
    }
    return [
        OperationalSignal(
            category=categories[item.instruction][0],
            summary=categories[item.instruction][1],
            start_line=item.start_line,
            end_line=item.end_line,
            text=f"{item.instruction} {item.arguments}".rstrip(),
            annotations={"instruction": item.instruction},
        )
        for item in parse_dockerfile(text)
        if item.instruction in categories
    ]


__all__ = [
    "DockerfileInstruction",
    "OperationalSignal",
    "find_operational_signals",
    "language_for_path",
    "parse_dockerfile",
]
