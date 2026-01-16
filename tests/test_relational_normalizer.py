import json
from pathlib import Path

from fetchgraph.relational import (
    ColumnDescriptor,
    EntityDescriptor,
    RelationalQuery,
    RelationDescriptor,
    RelationJoin,
    normalize_relational_query,
)


def _build_schema():
    customers = EntityDescriptor(
        name="customers",
        columns=[
            ColumnDescriptor(name="customer_id"),
            ColumnDescriptor(name="name"),
            ColumnDescriptor(name="city"),
        ],
    )
    orders = EntityDescriptor(
        name="orders",
        columns=[
            ColumnDescriptor(name="order_id"),
            ColumnDescriptor(name="customer_id"),
        ],
    )
    relations = [
        RelationDescriptor(
            name="customer_orders",
            from_entity="customers",
            to_entity="orders",
            join=RelationJoin(
                from_entity="customers",
                from_column="customer_id",
                to_entity="orders",
                to_column="customer_id",
            ),
        )
    ]
    return [customers, orders], relations


def test_normalize_relational_query_corpus():
    entities, relations = _build_schema()
    corpus_path = Path(__file__).parent / "data" / "relational_query_corpus.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    for entry in corpus:
        req = RelationalQuery.model_validate(entry["input"])
        normalized = normalize_relational_query(
            req, entities=entities, relations=relations
        )
        expected = entry["expected"]
        assert normalized.root_entity == expected["root_entity"]
        assert [sel.model_dump() for sel in normalized.select] == expected["select"]
        if "filters" in expected:
            assert normalized.filters is not None
            assert normalized.filters.model_dump() == expected["filters"]
        if "limit" in expected:
            assert normalized.limit == expected["limit"]
        if "offset" in expected:
            assert normalized.offset == expected["offset"]
