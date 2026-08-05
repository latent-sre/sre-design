"""Per-service upstream/downstream dependency maps: the single-service page (honest about
what one repo can't see) and the estate page (both directions resolved across repos).

Attribution discipline is the point under test: failure sentences attach to a bound
resource only via a direct sink match or the sole-binding-of-type rule; everything
repo-derived renders sanitized; the single-repo upstream section never invents callers.
"""

from __future__ import annotations

from sre_kb.render.depmap import dependency_map_markdown, estate_dependency_map_markdown

SERVICE = "order-service"

DOCS = [
    {"kind": "Topology", "metadata": {"name": SERVICE, "service": SERVICE}, "spec": {
        "nodes": [
            {"type": "service", "name": SERVICE},
            {"type": "datastore", "name": "orders-postgres"},
            {"type": "broker", "name": "order-kafka"},
            {"type": "external", "name": "inventory"},
            {"type": "topic", "name": "order.created"},
        ],
        "edges": [
            {"from": SERVICE, "to": "orders-postgres", "relation": "binds"},
            {"from": SERVICE, "to": "order-kafka", "relation": "binds"},
            {"from": SERVICE, "to": "inventory", "relation": "calls"},
            {"from": SERVICE, "to": "order.created", "relation": "publishes"},
        ],
    }},
    {"kind": "Flow", "metadata": {"name": "create-order", "service": SERVICE}, "spec": {
        "trigger": {"method": "POST", "path": "/api/v1/orders"},
        "steps": [
            {"id": "s1", "name": "call-reserve", "kind": "http-egress",
             "failureModes": [{"mode": "timeout", "surfacedAs": "http-503"}]},
            {"id": "s2", "name": "persist", "kind": "db-write",
             "failureModes": [{"mode": "db-unavailable", "surfacedAs": "http-500"}]},
        ],
        "sinks": [{"type": "http", "target": "inventory"},
                  {"type": "db", "target": "order-repository"}],
    }},
    {"kind": "BlastRadius", "metadata": {"name": "order-created", "service": SERVICE}, "spec": {
        "node": {"type": "broker", "name": "order.created"},
        "impactedFlows": ["create-order"],
        "containment": [],
        "stateful": {"dataLossRisk": True},
        "severityHint": "high",
    }},
    {"kind": "ServiceCatalogEntry", "metadata": {"name": SERVICE, "service": SERVICE},
     "spec": {"providesApis": ["/api/v1/orders"]}},
    {"kind": "Messaging", "metadata": {"name": "messaging", "service": SERVICE},
     "spec": {"consumers": [{"channel": "payment.settled", "broker": "order-kafka",
                             "handler": "onSettled"}]}},
]


def test_downstream_rows_carry_plain_english_failures():
    md = dependency_map_markdown(SERVICE, DOCS)
    inventory_row = next(line for line in md.splitlines() if line.startswith("| `inventory`"))
    assert "If the call takes too long (timeout)" in inventory_row
    assert "HTTP 503" in inventory_row


def test_sole_binding_of_type_attributes_db_sink_to_the_only_datastore():
    md = dependency_map_markdown(SERVICE, DOCS)
    pg_row = next(line for line in md.splitlines() if line.startswith("| `orders-postgres`"))
    # The db-write sink names `order-repository` (code side); the sole bound datastore is
    # where the write can only be going — the same rule the estate impact join uses.
    assert "If the database is unreachable" in pg_row


def test_two_datastores_attribute_nothing_rather_than_guess():
    docs = [dict(DOCS[0], spec={
        "nodes": DOCS[0]["spec"]["nodes"] + [{"type": "datastore", "name": "audit-db"}],
        "edges": DOCS[0]["spec"]["edges"] + [
            {"from": SERVICE, "to": "audit-db", "relation": "binds"}],
    })] + DOCS[1:]
    md = dependency_map_markdown(SERVICE, docs)
    pg_row = next(line for line in md.splitlines() if line.startswith("| `orders-postgres`"))
    assert "(no failure modes detected in code)" in pg_row  # ambiguity renders nothing


def test_blast_radius_line_joins_data_loss_and_severity():
    md = dependency_map_markdown(SERVICE, DOCS)
    topic_row = next(line for line in md.splitlines() if line.startswith("| `order.created`"))
    assert "**loses data**" in topic_row and "severity hint: high" in topic_row
    assert "no containment" in topic_row


def test_upstream_section_is_honest_and_lists_what_one_repo_knows():
    md = dependency_map_markdown(SERVICE, DOCS)
    up = md.split("## Upstream")[1]
    assert "- `/api/v1/orders`" in up                       # entry points callers use
    assert "`payment.settled`" in up                        # consumed topics (upstream feed)
    assert "cannot see its callers" in up and "sre-kb estate" in up


def test_untrusted_names_render_sanitized():
    evil = "bad`name\n[x](y)"
    docs = [{"kind": "Topology", "metadata": {"name": SERVICE}, "spec": {
        "nodes": [{"type": "service", "name": SERVICE}, {"type": "external", "name": evil}],
        "edges": [{"from": SERVICE, "to": evil, "relation": "calls"}],
    }}]
    md = dependency_map_markdown(SERVICE, docs)
    assert "bad`name" not in md and "badname [x](y)" in md  # backticks stripped, one line


ESTATE_TOPO = {"kind": "Topology", "metadata": {"name": "estate"}, "spec": {
    "nodes": [
        {"type": "service", "name": "order-service"},
        {"type": "service", "name": "billing-service"},
        {"type": "datastore", "name": "orders-postgres"},
        {"type": "topic", "name": "order.created"},
        {"type": "external", "name": "inventory"},
    ],
    "edges": [
        {"from": "order-service", "to": "orders-postgres", "relation": "binds"},
        {"from": "billing-service", "to": "orders-postgres", "relation": "binds"},
        {"from": "billing-service", "to": "order-service", "relation": "calls",
         "contract": "openapi"},
        {"from": "order-service", "to": "inventory", "relation": "calls"},
        {"from": "order-service", "to": "order.created", "relation": "publishes"},
        {"from": "order.created", "to": "billing-service", "relation": "consumes"},
    ],
}}
ESTATE_BLAST = {"kind": "BlastRadius", "metadata": {"name": "orders-postgres-cotenancy"}, "spec": {
    "node": {"type": "datastore", "name": "orders-postgres"},
    "coTenancy": [{"sharedBy": ["billing-service", "order-service"]}],
    "indirectServices": ["frontend-app"],
}}


def test_estate_map_resolves_both_directions_per_service():
    md = estate_dependency_map_markdown(ESTATE_TOPO, [ESTATE_BLAST])
    order = md.split("## `order-service`")[1]
    assert "`billing-service` calls `order-service` over HTTP" in order
    assert "`billing-service` consumes `order.created`" in order
    assert "shares `orders-postgres` with `billing-service`" in order
    assert "indirect reach via call chains: `frontend-app`" in order

    billing = md.split("## `billing-service`")[1].split("## `order-service`")[0]
    assert "contract: OpenAPI" in billing                    # its call edge carries the contract
    assert "consumes events from (published by `order-service`)" in billing


def test_estate_map_states_when_no_scanned_caller_exists():
    topo = {"kind": "Topology", "metadata": {"name": "estate"}, "spec": {
        "nodes": [{"type": "service", "name": "solo"}], "edges": []}}
    md = estate_dependency_map_markdown(topo, [])
    assert "no scanned service depends on it" in md
    assert "- (none detected)" in md
