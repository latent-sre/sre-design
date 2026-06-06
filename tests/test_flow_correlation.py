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
