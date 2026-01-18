from fetchgraph.relational.dsl import (
    ColumnRef,
    Comparison,
    Logical,
    OrderBy,
    SelectItem,
    SelectQuery,
    SelectStar,
    normalize_query,
)


def test_normalize_select_star_with_schema() -> None:
    query = SelectQuery(
        select=[SelectItem(expr=SelectStar())],
        from_table="Users",
    )

    normalized = normalize_query(query, table_columns={"users": ["Id", "Name"]})

    assert [item.expr for item in normalized.select] == [
        ColumnRef(table="users", name="id"),
        ColumnRef(table="users", name="name"),
    ]


def test_normalize_filters_and_order_by() -> None:
    query = SelectQuery(
        select=[SelectItem(expr=ColumnRef(table="Users", name="Email"), alias="Mail")],
        from_table="Users",
        where=Logical(
            op="AND",
            clauses=[
                Comparison(
                    left=ColumnRef(table="Users", name="Age"),
                    op=">=",
                    right=ColumnRef(table="Users", name="MinAge"),
                ),
                Comparison(
                    left=ColumnRef(table="Users", name="Status"),
                    op="EQ",
                    right=ColumnRef(table="Users", name="Active"),
                ),
            ],
        ),
        order_by=[OrderBy(column=ColumnRef(table="Users", name="Email"), direction="DESC")],
        limit=-10,
        offset=-1,
    )

    normalized = normalize_query(query)

    assert normalized.select == [
        SelectItem(expr=ColumnRef(table="users", name="email"), alias="mail")
    ]
    assert normalized.where == Logical(
        op="and",
        clauses=[
            Comparison(
                left=ColumnRef(table="users", name="age"),
                op=">=",
                right=ColumnRef(table="users", name="minage"),
            ),
            Comparison(
                left=ColumnRef(table="users", name="status"),
                op="=",
                right=ColumnRef(table="users", name="active"),
            ),
        ],
    )
    assert normalized.order_by == [
        OrderBy(column=ColumnRef(table="users", name="email"), direction="desc")
    ]
    assert normalized.limit == 0
    assert normalized.offset == 0
