"""In-process structural search and operational-file parsing contracts."""

from __future__ import annotations

import inspect

import pytest

from sre_kb.parsing.code_model import syntax_matches, syntax_tree
from sre_kb.parsing.operational import (
    DockerfileInstruction,
    find_operational_signals,
    parse_dockerfile,
)
from sre_kb.parsing.structural import (
    StructuralQueryError,
    StructuralRule,
    find_structural_matches,
)


@pytest.mark.parametrize(
    ("language", "source", "root_kind"),
    [
        ("bash", "curl https://status.example\n", "program"),
        ("sql", "CREATE TABLE jobs (id INT);\n", "program"),
        ("yaml", "services:\n  api:\n    image: example/api\n", "stream"),
    ],
)
def test_new_mit_grammars_parse_in_process(language: str, source: str, root_kind: str):
    tree, encoded = syntax_tree(language, source)

    assert tree.root_node.type == root_kind
    assert encoded == source.encode("utf-8")


def test_tree_sitter_query_matches_return_exact_named_captures():
    matches = syntax_matches(
        "bash",
        "curl https://status.example\nsystemctl restart api\n",
        "(command name: (command_name) @command)",
    )

    assert [capture.text for match in matches for capture in match.captures["command"]] == [
        "curl",
        "systemctl",
    ]
    assert matches[0].captures["command"][0].start_line == 1
    assert matches[1].captures["command"][0].start_line == 2


def test_ast_grep_search_preserves_spans_and_captures():
    rule = StructuralRule(
        rule_id="test.member-call",
        category="test",
        summary="member call",
        languages=frozenset({"python"}),
        configs=({"pattern": "$RECEIVER.$METHOD($$$ARGS)"},),
        captures=("RECEIVER", "METHOD"),
    )

    matches = find_structural_matches(
        "client.fetch('/health')\nclient.fetch('/ready')\n",
        "python",
        [rule],
    )

    assert [(match.start_line, match.end_line) for match in matches] == [(1, 1), (2, 2)]
    assert matches[0].captures == {"METHOD": ("fetch",), "RECEIVER": ("client",)}
    assert matches[0].text == "client.fetch('/health')"


def test_ast_grep_adapter_rejects_unsupported_languages_before_native_dispatch():
    rule = StructuralRule(
        rule_id="test.any",
        category="test",
        summary="test",
        languages=frozenset({"sql"}),
        configs=({"kind": "statement"},),
    )

    with pytest.raises(StructuralQueryError, match="not supported"):
        find_structural_matches("select 1", "sql", [rule])


def test_structural_adapter_has_no_process_dynamic_language_or_rewrite_surface():
    import sre_kb.parsing.structural as structural

    source = inspect.getsource(structural)
    assert "subprocess" not in source
    assert "register_dynamic_language" not in source
    assert "commit_edits" not in source
    assert "replace(" not in source
    assert structural.EXECUTION_MODEL == "in-process/read-only"


@pytest.mark.parametrize(
    ("language", "source", "category"),
    [
        ("python", 'subprocess.run(["systemctl", "restart", "api"])\n', "process.exec"),
        ("javascript", 'fetch("https://status.example")\n', "network.client"),
        ("typescript", "const url = process.env.API_URL\n", "config.environment"),
        ("java", 'Runtime.getRuntime().exec("service api restart");\n', "process.exec"),
        ("csharp", 'Process.Start("systemctl", "restart api");\n', "process.exec"),
        (
            "go",
            'package main\nfunc main() { http.Get("https://status.example") }\n',
            "network.client",
        ),
        ("bash", "kubectl rollout status deployment/api\n", "service.control"),
    ],
)
def test_operational_call_classifier_is_cross_language(
    language: str,
    source: str,
    category: str,
):
    signals = find_operational_signals(language, source)

    assert category in {signal.category for signal in signals}
    assert all(
        signal.start_line >= 1 and signal.evidence_class == "STATIC_EXTRACTED" for signal in signals
    )


def test_operational_receiver_matching_does_not_use_substrings():
    signals = find_operational_signals(
        "python",
        "catalog.error('not a logger')\nrepository.run()\n",
    )

    assert signals == []


def test_sql_and_yaml_operational_signals_use_their_tree_sitter_grammars():
    sql = find_operational_signals(
        "sql",
        "CREATE TABLE jobs(id INT);\nUPDATE jobs SET id = 2;\n",
    )
    yaml = find_operational_signals(
        "yaml",
        "services:\n  api:\n    image: example/api\n    healthcheck:\n      test: curl /health\n",
    )

    assert {signal.category for signal in sql} == {
        "database.mutation",
        "database.schema-change",
    }
    assert "deployment.healthcheck" in {signal.category for signal in yaml}
    assert "deployment.image" in {signal.category for signal in yaml}


def test_dockerfile_parser_handles_continuations_without_running_docker():
    text = """\
FROM python:3.13-slim AS runtime
RUN apt-get update && \\
    apt-get install -y curl
HEALTHCHECK CMD curl --fail http://localhost:8080/health
USER 10001
"""

    instructions = parse_dockerfile(text)

    assert instructions == [
        DockerfileInstruction("FROM", "python:3.13-slim AS runtime", 1, 1),
        DockerfileInstruction("RUN", "apt-get update && apt-get install -y curl", 2, 3),
        DockerfileInstruction(
            "HEALTHCHECK",
            "CMD curl --fail http://localhost:8080/health",
            4,
            4,
        ),
        DockerfileInstruction("USER", "10001", 5, 5),
    ]
    categories = {signal.category for signal in find_operational_signals("dockerfile", text)}
    assert {"deployment.base-image", "deployment.healthcheck", "deployment.user"} <= categories
