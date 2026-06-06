"""Regression tests for bugs an independent review found — inputs deliberately shaped to
deviate from the happy-path fixtures (K&R braces, route-arg'd HTTP attrs, multi-target
csproj, DI-style breaker, quoted sourcetype, unquoted/placeholder secrets, token in stderr).
Each of these failed before the corresponding fix."""

from __future__ import annotations

import pytest

from sre_kb.collectors.dotnet_steeltoe.annotations import _HTTP, _detect_swallowed
from sre_kb.collectors.dotnet_steeltoe.build import _TFM
from sre_kb.collectors.dotnet_steeltoe.resiliency import _method_using
from sre_kb.publish.forge.base import ForgePublishError
from sre_kb.publish.forge.github import GitHubForge
from sre_kb.security.secret_scan import scan_text
from sre_kb.validation.challenge import extract_claims


# --- HIGH: .NET collector regex brittleness ---

def test_swallowed_detection_handles_knr_braces():
    knr = [
        "try {",
        '    await _producer.ProduceAsync("orders.created", m);',
        "} catch (Exception ex) {",
        '    _logger.LogError(ex, "failed to publish orders.created");',
        "}",
    ]
    sw = _detect_swallowed(knr, 1)
    assert sw is not None and "failed to publish" in sw["message"]


def test_swallowed_detection_still_handles_allman_braces():
    allman = [
        "try",
        "{",
        '    await _producer.ProduceAsync("t", m);',
        "}",
        "catch (Exception ex)",
        "{",
        '    _logger.LogError(ex, "boom");',
        "}",
    ]
    assert _detect_swallowed(allman, 2)["message"] == "boom"


def test_swallowed_detection_respects_rethrow():
    rethrow = ["try {", '    _producer.Produce("t", m);', "} catch (Exception ex) {",
               '    _logger.LogError(ex, "x");', "    throw;", "}"]
    assert _detect_swallowed(rethrow, 1) is None  # rethrown => not swallowed


@pytest.mark.parametrize("attr,verb", [
    ("[HttpPost]", "Post"),
    ('[HttpGet("{id}")]', "Get"),
    ('[HttpPost("orders")]', "Post"),
    ('[HttpGet(Name = "x")]', "Get"),
])
def test_http_attribute_matches_route_args(attr, verb):
    m = _HTTP.search(attr)
    assert m is not None and m.group(1) == verb


def test_http_attribute_extracts_route_literal():
    assert _HTTP.search('[HttpGet("{id}")]').group(2) == "{id}"
    assert _HTTP.search("[HttpPost]").group(2) is None


def test_multi_target_csproj_framework_detected():
    assert _TFM.search("<TargetFrameworks>net6.0;net8.0</TargetFrameworks>").group(1).startswith("net6.0")
    assert _TFM.search("<TargetFramework>net6.0</TargetFramework>").group(1) == "net6.0"


def test_breaker_target_is_the_method_that_uses_it_not_textual_next():
    # fallback method is declared BEFORE the protected method, and the breaker is registered
    # in the ctor — so "next textual public method" would wrongly pick ReserveFallback.
    lines = [
        "public InventoryClient() {",
        "    _breaker = Policy.Handle<Exception>().CircuitBreakerAsync(5, t);",
        "}",
        "public Task ReserveFallback() { return Task.CompletedTask; }",
        "public async Task ReserveAsync() {",
        "    await _breaker.ExecuteAsync(() => Call());",
        "}",
    ]
    target, _ = _method_using(lines, "_breaker.")
    assert target == "ReserveAsync"


# --- MED: challenge needle decoupled from sourcetype quoting ---

def test_alert_needle_picks_log_message_even_with_quoted_sourcetype():
    doc = {"kind": "Alert", "evidence": [{}], "spec": {
        "signalSource": "log-pattern",
        "expr": {"splunk": 'index=app sourcetype="orders-service" "failed to publish the order event"'},
    }}
    assert extract_claims(doc)[0].needle == "failed to publish the order event"


# --- MED: secret scanner coverage + placeholder false positives ---

def test_secret_scan_catches_unquoted_and_fine_grained_pat():
    assert any(f["rule"] == "assigned-secret-unquoted" for f in scan_text("DB_PASSWORD=hunter2pass99", "e"))
    assert any(f["rule"] == "github-fine-grained-pat" for f in scan_text("t=github_pat_" + "A" * 30, "e"))


def test_secret_scan_ignores_obvious_placeholders():
    assert scan_text('token: "replace-with-your-token"', "c") == []
    assert scan_text("Authorization: Bearer YOUR_TOKEN_HERE_PLACEHOLDER", "c") == []
    assert scan_text("password = changeme", "c") == []
    # but a real-looking secret is still caught
    assert scan_text('password = "8sJ2kLp93xZqW"', "c")


# --- MED: forge token never leaks via stderr; empty tree handled ---

def test_forge_redacts_token_in_stderr():
    # _default_run redacts git stderr through _redact; a tokenized remote URL must not leak.
    from sre_kb.publish.forge.github import _redact

    leaked = "fatal: could not read from https://x-access-token:ghp_SECRETTOKEN@github.com/o/r.git"
    assert "ghp_SECRETTOKEN" not in _redact([leaked])[0]
    assert "x-access-token:***@" in _redact([leaked])[0]


def test_forge_empty_tree_raises_clear_error(tmp_path):
    (tmp_path / "f.txt").write_text("x")

    def runner(cmd):
        return "main\n" if "rev-parse" in cmd else ""  # status --porcelain => empty

    with pytest.raises(ForgePublishError, match="nothing to publish"):
        GitHubForge(runner=runner, http_post=lambda *a: {}, token="T").open_pr(
            tmp_path, sre_repo="o/r", branch="b", title="t", body="x"
        )
