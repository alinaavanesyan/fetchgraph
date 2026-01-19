from fetchgraph.relational.normalize import normalize_relational_selectors


def test_normalize_aggregations_infers_agg() -> None:
    selectors = {
        "op": "query",
        "root_entity": "orders",
        "aggregations": [{"field": "count(*)", "alias": "count"}],
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["aggregations"] == [{"field": "*", "agg": "count", "alias": "count"}]


def test_normalize_filters_list_to_logical() -> None:
    selectors = {
        "op": "query",
        "root_entity": "customers",
        "filters": [
            {"type": "comparison", "field": "customer_id", "op": "=", "value": "914"},
        ],
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["filters"] == {
        "type": "comparison",
        "field": "customer_id",
        "op": "=",
        "value": "914",
    }


def test_normalize_min_filter_to_aggregation() -> None:
    selectors = {
        "op": "query",
        "root_entity": "orders",
        "filters": {
            "type": "comparison",
            "field": "order_total",
            "op": "min",
        },
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["filters"] is None
    assert normalized["aggregations"] == [
        {"field": "order_total", "agg": "min", "alias": "min_order_total"}
    ]


def test_normalize_group_by_filters_empty_fields() -> None:
    selectors = {
        "op": "query",
        "root_entity": "order_items",
        "group_by": [
            {"entity": None, "field": None, "alias": None},
            {"entity": "order_items", "field": "product_id", "alias": None},
        ],
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["group_by"] == [
        {"entity": "order_items", "field": "product_id", "alias": None}
    ]


def test_normalize_filters_flattens_nested_lists() -> None:
    selectors = {
        "op": "query",
        "root_entity": "orders",
        "filters": [
            [
                {"type": "comparison", "field": "customer_id", "op": "=", "value": "722"},
            ]
        ],
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["filters"] == {
        "type": "comparison",
        "field": "customer_id",
        "op": "=",
        "value": "722",
    }


def test_normalize_aggregations_handles_strings_and_none() -> None:
    selectors = {
        "op": "query",
        "root_entity": "orders",
        "aggregations": ["count(order_id)", None],
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["aggregations"] == [
        {"field": "order_id", "agg": "count", "alias": None}
    ]


def test_normalize_group_by_accepts_string() -> None:
    selectors = {
        "op": "query",
        "root_entity": "orders",
        "group_by": ["country"],
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["group_by"] == [{"entity": None, "field": "country", "alias": None}]


def test_normalize_filters_logical_op_lowercases_and_flattens() -> None:
    selectors = {
        "op": "query",
        "root_entity": "orders",
        "filters": {
            "type": "logical",
            "op": "AND",
            "clauses": [[{"type": "comparison", "field": "id", "op": "=", "value": "1"}]],
        },
    }

    normalized = normalize_relational_selectors(selectors)

    assert normalized["filters"] == {
        "type": "logical",
        "op": "and",
        "clauses": [{"type": "comparison", "field": "id", "op": "=", "value": "1"}],
    }
