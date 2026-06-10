"""AST code model: precise multi-class scoping, receiver->field-type resolution, and
string-arg extraction — the things the line regexes got wrong."""

from __future__ import annotations

from sre_kb.parsing import parse


def test_scancontext_module_is_parsed_once_and_shared(tmp_path, monkeypatch):
    """Every collector shares one parse per (file, language) via ctx.module — the Java collectors
    alone otherwise re-parse each *.java up to ~5x per scan."""
    import sre_kb.collectors.base as base

    (tmp_path / "A.java").write_text("package p; class A { void go() {} }", encoding="utf-8")
    ctx = base.ScanContext(root=tmp_path, repo="file://x")

    calls = 0
    real = base.parse

    def counting(language, text):
        nonlocal calls
        calls += 1
        return real(language, text)

    monkeypatch.setattr(base, "parse", counting)
    first = ctx.module("A.java", "java")
    again = ctx.module("A.java", "java")
    assert first is again      # same parsed object handed back
    assert calls == 1          # parsed once despite repeated requests


def test_java_scopes_each_class_separately():
    # the old _TYPE first-match bug attributed everything to the first class; the AST does not.
    src = """
package p;
class Helper { void h() {} }
class Service {
    private final Repo repo;
    void doIt() { repo.save(thing); }
}
"""
    m = parse("java", src)
    assert [t.name for t in m.types] == ["Helper", "Service"]
    svc = next(t for t in m.types if t.name == "Service")
    assert svc.fields == {"repo": "Repo"}
    assert ("repo", "save") in [(c.receiver, c.method) for mth in svc.methods for c in mth.calls]


def test_java_resolves_receiver_to_field_type():
    src = "package p; class C { private final OrderEventPublisher pub; void go() { pub.publish(e); } }"
    c = parse("java", src).types[0]
    call = c.methods[0].calls[0]
    assert c.fields[call.receiver] == "OrderEventPublisher"


def test_java_extracts_string_args_for_topic_resolution():
    c = parse("java", 'class C { void go() { producer.send("orders.created", x); } }').types[0]
    assert "orders.created" in c.methods[0].calls[0].str_args


def test_string_arg_keeps_leading_placeholder_dollar():
    # A both-ends strip("\"'@$") mangled a Spring placeholder topic "${topic.name}" into
    # "{topic.name}", corrupting the egress channel name and its de-dup key. The $ must survive.
    c = parse("java", 'class C { void go() { producer.send("${topic.name}", x); } }').types[0]
    assert "${topic.name}" in c.methods[0].calls[0].str_args


def test_csharp_interpolated_string_prefix_is_dropped_but_inner_dollar_kept():
    # C# $"..." / @"..." prefixes are stripped; a $ inside the value is not.
    c = parse("csharp", 'class C { void Go() { p.Send($"orders.${x}", e); } }').types[0]
    assert "orders.${x}" in c.methods[0].calls[0].str_args


def test_deeply_nested_expression_does_not_abort_the_scan():
    # A hostile target file with a deeply nested expression once raised RecursionError out of the
    # recursive _descend walk, aborting the whole scan. The iterative walk must parse it without
    # blowing the recursion limit. (Depth chosen well above sys.getrecursionlimit().)
    depth = 5000
    src = "function f() { return " + "(" * depth + "1" + ")" * depth + "; }"
    m = parse("javascript", src)
    assert m is not None


def test_csharp_class_fields_and_calls():
    src = """
namespace N;
public class C {
    private readonly OrderPublisher _publisher;
    public async Task Go() { await _publisher.PublishAsync(e); }
}
"""
    c = parse("csharp", src).types[0]
    assert c.fields["_publisher"] == "OrderPublisher"
    assert any(call.method == "PublishAsync" and call.receiver == "_publisher"
               for mth in c.methods for call in mth.calls)


def test_collector_attributes_facts_to_the_enclosing_class(tmp_path):
    # A helper class is declared FIRST and the controller SECOND. The old first-match
    # attribution mislabeled the endpoint with the helper class; AST scoping gets it right.
    from sre_kb.collectors.base import ScanContext
    from sre_kb.collectors.java_spring import annotations

    src = """package com.acme.demo;
import org.springframework.web.bind.annotation.*;

class OrderHelper { void noop() {} }

@RestController
@RequestMapping("/api/widgets")
class WidgetController {
    @PostMapping
    public String create() { return "ok"; }
}
"""
    pkg = tmp_path / "src"
    pkg.mkdir()
    (pkg / "WidgetController.java").write_text(src)
    facts = annotations.collect(ScanContext(root=tmp_path, repo="file://t"))
    eps = [f for f in facts if f.type == "rest.endpoint"]
    assert eps and eps[0].attrs["handler"] == "com.acme.demo.WidgetController#create"
    assert "OrderHelper" not in eps[0].attrs["handler"]


def _send_call(src: str):
    return next(c for c in parse("java", src).types[0].methods[0].calls if c.method == "send")


def test_swallow_needs_a_real_log_call_not_a_log_substring():
    # `catalog` contains "log" but `catalog.update(e)` in a catch is NOT a logged-and-swallowed
    # failure (the old substring test misfired here and seeded a spurious data-loss claim).
    false_pos = "class C { void go() { try { q.send(x); } catch (Exception e) { catalog.update(e); } } }"
    assert _send_call(false_pos).swallow is None

    real = 'class C { void go() { try { q.send(x); } catch (Exception e) { log.error("boom", e); } } }'
    sw = _send_call(real).swallow
    assert sw is not None and sw.message == "boom"


def test_swallow_detected_in_a_later_catch_clause():
    # A logged-and-swallowed failure in a non-first catch is still data loss (was missed:
    # only the first catch_clause was inspected).
    src = ("class C { void go() { try { q.send(x); } "
           "catch (IllegalStateException e) { throw e; } "
           'catch (Exception e) { logger.warn("dropped", e); } } }')
    sw = _send_call(src).swallow
    assert sw is not None and sw.message == "dropped"



def test_nested_try_catch_not_attributed_to_enclosing_catch():
    """#M6: a nested try/catch's throw/log must not be judged as the enclosing catch's. (a) an outer
    catch that logs-and-swallows is detected even when an inner catch rethrows; (b) an inner catch's
    log is not mis-attributed as the outer catch swallowing."""
    from sre_kb.parsing import parse

    # (a) outer logs + swallows; nested catch rethrows -> the inner throw must not mask the swallow
    src_a = (
        "class C {\n"
        "  void go() {\n"
        "    try { publisher.publish(evt); }\n"
        "    catch (Exception e) {\n"
        '      log.error("failed to publish");\n'
        "      try { cleanup(); } catch (Exception e2) { throw e2; }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    publish = next(c for m in parse("java", src_a).types[0].methods for c in m.calls if c.method == "publish")
    assert publish.swallow is not None and publish.swallow.message == "failed to publish"

    # (b) outer neither logs nor rethrows directly; only a nested catch logs -> NOT an outer swallow
    src_b = (
        "class C {\n"
        "  void go() {\n"
        "    try { repo.save(x); }\n"
        "    catch (Exception e) {\n"
        '      try { other(); } catch (Exception e2) { log.error("inner only"); }\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    save = next(c for m in parse("java", src_b).types[0].methods for c in m.calls if c.method == "save")
    assert save.swallow is None


def test_csharp_nested_class_members_not_attributed_to_outer():
    """#M5: C# method/field extraction is direct-children-only (like Java), so a nested class's
    members belong to the nested TypeDecl, not the enclosing one (was double-attributed via _descend)."""
    from sre_kb.parsing import parse

    src = (
        "namespace A {\n"
        "  public class Outer {\n"
        "    private readonly Foo foo;\n"
        "    public void Handle() { foo.Do(); }\n"
        "    class Nested {\n"
        "      private readonly Bar bar;\n"
        "      public void Inner() { bar.Go(); }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    types = {t.name: t for t in parse("csharp", src).types}
    assert [m.name for m in types["Outer"].methods] == ["Handle"]
    assert list(types["Outer"].fields) == ["foo"]
    assert [m.name for m in types["Nested"].methods] == ["Inner"]
    assert list(types["Nested"].fields) == ["bar"]
