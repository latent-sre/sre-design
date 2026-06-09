"""S4 quick win: Tier-A missing-idempotency gaps on mutating routes."""

from __future__ import annotations

from pathlib import Path

from sre_kb.collectors import scan
from sre_kb.collectors.base import ScanContext
from sre_kb.collectors.common import idempotency
from sre_kb.models.facts import Fact, FactSet, Symbol

SPRING = Path(__file__).parent / "fixtures" / "sample-spring-pcf"


def test_unguarded_post_route_is_a_tier_a_gap():
    ctx = ScanContext(root=SPRING, repo="file://sample-spring-pcf")
    fs = scan(ctx)
    gaps = idempotency.collect_gaps(ctx, fs)
    cats = {(g.attrs["category"], g.attrs["rederivation"]) for g in gaps}
    assert ("missing-idempotency", "mutating-route") in cats
    g = next(g for g in gaps if g.attrs["category"] == "missing-idempotency")
    assert g.evidence.source_tier == "ast"          # Tier-A: can verify
    assert "POST" in g.attrs["rationale"]


def test_get_route_is_never_a_gap():
    ctx = ScanContext(root=SPRING, repo="file://sample-spring-pcf")
    fs = FactSet()
    fs.add(Fact(
        "rest.endpoint",
        {"method": "GET", "path": "/api/v1/orders", "handler": "list"},
        ctx.evidence("src/main/java/com/acme/order/web/OrderController.java", 29, 29, "x"),
        Symbol("list", "method"),
    ))
    assert idempotency.collect_gaps(ctx, fs) == []   # reads are idempotent by definition


def test_guard_in_scope_refutes_the_gap(tmp_path):
    src = (
        "package x;\n"
        "@RestController class C {\n"
        "  @PostMapping public void create() {\n"
        "    if (store.seen(idempotencyKey)) return;\n"   # idempotency guard in scope
        "  }\n"
        "}\n"
    )
    rel = "C.java"
    (tmp_path / rel).write_text(src, encoding="utf-8")
    ctx = ScanContext(root=tmp_path, repo="file://x")
    fs = FactSet()
    fs.add(Fact("rest.endpoint", {"method": "POST", "path": "/c", "handler": "x.C#create"},
                ctx.evidence(rel, 3, 3, "t"), Symbol("x.C#create", "method")))
    assert idempotency.collect_gaps(ctx, fs) == []   # guard present -> no gap
