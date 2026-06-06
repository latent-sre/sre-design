"""AST code model: precise multi-class scoping, receiver->field-type resolution, and
string-arg extraction — the things the line regexes got wrong."""

from __future__ import annotations

from sre_kb.parsing import parse


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
