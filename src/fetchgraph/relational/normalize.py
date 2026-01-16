from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .models import (
    ComparisonFilter,
    EntityDescriptor,
    FilterClause,
    LogicalFilter,
    RelationDescriptor,
    RelationalQuery,
    SelectExpr,
)


@dataclass(frozen=True)
class RelationalNormalizeOptions:
    expand_select_star: bool = True
    normalize_identifiers: bool = True
    normalize_operators: bool = True
    normalize_limits: bool = True


_OPERATOR_ALIASES = {
    "==": "=",
    "===": "=",
    "!=": "!=",
    "<>": "!=",
    "lte": "<=",
    "gte": ">=",
}


def normalize_relational_query(
    req: RelationalQuery,
    *,
    entities: Iterable[EntityDescriptor],
    relations: Iterable[RelationDescriptor],
    options: Optional[RelationalNormalizeOptions] = None,
) -> RelationalQuery:
    opts = options or RelationalNormalizeOptions()
    entity_map = {ent.name.lower(): ent for ent in entities}
    relation_map = {rel.name.lower(): rel.name for rel in relations}

    root_entity = req.root_entity
    if opts.normalize_identifiers:
        resolved_root = entity_map.get(req.root_entity.lower())
        if resolved_root:
            root_entity = resolved_root.name

    columns = []
    resolved_entity = entity_map.get(root_entity.lower())
    if resolved_entity:
        columns = [col.name for col in resolved_entity.columns]
    column_map = {col.lower(): col for col in columns}

    def normalize_field(entity: Optional[str], field: str) -> tuple[Optional[str], str]:
        ent = entity
        fld = field
        if "." in field:
            ent, fld = field.split(".", 1)
        if opts.normalize_identifiers and ent:
            ent = entity_map.get(ent.lower(), EntityDescriptor(name=ent)).name
        if opts.normalize_identifiers:
            fld = column_map.get(fld.lower(), fld)
        return ent, fld

    def normalize_select(expr: SelectExpr) -> list[SelectExpr]:
        raw = expr.expr.strip()
        if opts.expand_select_star and raw in {"*", f"{root_entity}.*"}:
            return [SelectExpr(expr=f"{root_entity}.{col}") for col in columns]
        ent, fld = normalize_field(root_entity, raw)
        expr_text = f"{ent}.{fld}" if ent else fld
        alias = expr.alias
        if alias and alias.lower() == fld.lower():
            alias = None
        return [SelectExpr(expr=expr_text, alias=alias)]

    def normalize_filter(filter_clause: FilterClause) -> FilterClause:
        if isinstance(filter_clause, ComparisonFilter):
            raw_field = filter_clause.field
            ent = filter_clause.entity
            if ent is None and "." not in raw_field:
                ent = root_entity
            ent, fld = normalize_field(ent, raw_field)
            op = filter_clause.op
            if opts.normalize_operators:
                op = _OPERATOR_ALIASES.get(op.lower(), op)
            value = filter_clause.value
            if isinstance(value, str):
                if (value.startswith("'") and value.endswith("'")) or (
                    value.startswith('"') and value.endswith('"')
                ):
                    value = value[1:-1]
            return ComparisonFilter(
                entity=ent,
                field=fld,
                op=op,
                value=value,
            )
        if isinstance(filter_clause, LogicalFilter):
            op = filter_clause.op.lower()
            return LogicalFilter(
                op=op,
                clauses=[normalize_filter(clause) for clause in filter_clause.clauses],
            )
        return filter_clause

    normalized_select: list[SelectExpr] = []
    if req.select:
        for expr in req.select:
            normalized_select.extend(normalize_select(expr))
    elif opts.expand_select_star:
        normalized_select = [SelectExpr(expr=f"{root_entity}.{col}") for col in columns]

    seen_exprs = set()
    deduped_select = []
    for expr in normalized_select:
        key = (expr.expr, expr.alias or "")
        if key in seen_exprs:
            continue
        seen_exprs.add(key)
        deduped_select.append(expr)

    normalized_filters = normalize_filter(req.filters) if req.filters else None

    normalized_relations = req.relations
    if opts.normalize_identifiers and req.relations:
        normalized_relations = [
            relation_map.get(rel.lower(), rel) for rel in req.relations
        ]

    limit = req.limit
    offset = req.offset
    if opts.normalize_limits:
        if limit is not None:
            try:
                limit = max(0, int(limit))
            except (TypeError, ValueError):
                limit = req.limit
        if offset is not None:
            try:
                offset = max(0, int(offset))
            except (TypeError, ValueError):
                offset = req.offset

    return req.model_copy(
        update={
            "root_entity": root_entity,
            "select": deduped_select,
            "filters": normalized_filters,
            "relations": normalized_relations,
            "limit": limit,
            "offset": offset,
        }
    )
