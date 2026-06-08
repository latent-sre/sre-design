"""AST-enabled correlation: a call is matched to the right fact by its receiver's field
type, so two publishers (or two clients sharing a method name) are disambiguated — which a
`.publish(` / `.reserve(` substring match could not do."""

from __future__ import annotations

from types import SimpleNamespace

from sre_kb.collectors.java_spring.flow_builder import _match_cb, _match_pub, _match_repo


def _f(**attrs):
    return SimpleNamespace(attrs=attrs)


def test_publisher_disambiguated_by_receiver_type():
    pubs = [
        _f(**{"class": "com.acme.OrderEventPublisher", "channel": "order.created"}),
        _f(**{"class": "com.acme.AuditPublisher", "channel": "audit.log"}),
    ]
    assert _match_pub(pubs, "OrderEventPublisher").attrs["channel"] == "order.created"
    assert _match_pub(pubs, "AuditPublisher").attrs["channel"] == "audit.log"  # not just the first


def test_circuit_breaker_matched_by_method_and_receiver_type():
    cbs = [
        _f(target="reserve", targetSymbol="com.acme.InventoryClient#reserve", name="inventory"),
        _f(target="reserve", targetSymbol="com.acme.PricingClient#reserve", name="pricing"),
    ]
    # both clients expose reserve(); the receiver's type selects the correct breaker
    assert _match_cb(cbs, "reserve", "PricingClient").attrs["name"] == "pricing"
    assert _match_cb(cbs, "reserve", "InventoryClient").attrs["name"] == "inventory"


def test_repo_matched_by_type_with_safe_fallback():
    repos = [_f(name="OrderRepository")]
    assert _match_repo(repos, "OrderRepository").attrs["name"] == "OrderRepository"
    assert _match_repo(repos, None).attrs["name"] == "OrderRepository"  # unresolved receiver -> sole repo
    assert _match_repo(repos, "SomethingElse") is None  # a save() on a non-repo type is not a db-write


def test_unresolved_receiver_among_many_is_not_guessed():
    # When the receiver's type can't be resolved AND there are several candidates, attribute
    # nothing — the old code blamed the first publisher/repo, fabricating an ungrounded sink.
    pubs = [
        _f(**{"class": "com.acme.OrderEventPublisher", "channel": "order.created"}),
        _f(**{"class": "com.acme.AuditPublisher", "channel": "audit.log"}),
    ]
    assert _match_pub(pubs, None) is None
    assert _match_pub(pubs[:1], None).attrs["channel"] == "order.created"  # sole candidate still ok

    repos = [_f(name="OrderRepository"), _f(name="AuditRepository")]
    assert _match_repo(repos, None) is None
    assert _match_repo(repos[:1], None).attrs["name"] == "OrderRepository"


def test_match_cb_does_not_guess_among_several_unresolved():
    """#M4: with an unresolved receiver and two breakers sharing a method name, attribute to neither
    (the breaker is ambiguous) — only a sole candidate or an exact field-type match is attributed."""
    from types import SimpleNamespace

    from sre_kb.collectors.java_spring.flow_builder import _match_cb

    cbs = [SimpleNamespace(attrs={"target": "reserve", "targetSymbol": "a.b.InventoryClient"}),
           SimpleNamespace(attrs={"target": "reserve", "targetSymbol": "a.b.PricingClient"})]
    assert _match_cb(cbs, "reserve", None) is None                  # ambiguous -> no guess
    assert _match_cb(cbs, "reserve", "PricingClient") is cbs[1]     # exact field-type match
    assert _match_cb(cbs[:1], "reserve", None) is cbs[0]            # sole candidate -> attributed
