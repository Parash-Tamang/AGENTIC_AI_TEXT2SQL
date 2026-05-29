from __future__ import annotations

from typing import Any

import sqlglot
import sqlglot.expressions as exp


def _normalize_table_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    return name.split(".")[-1].lower()


def _normalize_mandatory_filters(
    mandatory_filters: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for table, rules in (mandatory_filters or {}).items():
        table_key = _normalize_table_name(str(table))
        if not table_key or not isinstance(rules, dict):
            continue

        table_rules: dict[str, dict[str, Any]] = {}
        for col, rule in rules.items():
            col_key = str(col).strip().lower()
            if not col_key:
                continue

            if isinstance(rule, dict):
                filter_type = str(rule.get("filter", "id"))
                values = rule.get("values")
            else:
                filter_type = "id"
                values = None

            if values is not None and not isinstance(values, list):
                values = [values]

            table_rules[col_key] = {"filter": filter_type, "values": values}

        normalized[table_key] = table_rules

    return normalized


def _literal(value: Any) -> exp.Literal:
    text = str(value).strip()
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return exp.Literal.number(text)
    return exp.Literal.string(text)


def enforce_mandatory_filters(
    sql: str,
    mandatory_filters: dict[str, dict[str, Any]] | None,
) -> tuple[str, dict[str, dict[str, list[str]]]]:
    tree = sqlglot.parse_one(sql, dialect="tsql")

    required = _normalize_mandatory_filters(mandatory_filters)

    table_alias: dict[str, str] = {}
    used_tables: set[str] = set()
    for table_expr in tree.find_all(exp.Table):
        bare = _normalize_table_name(table_expr.name or "")
        if not bare:
            continue
        used_tables.add(bare)
        alias = (table_expr.alias_or_name or "").strip()
        table_alias[bare] = alias or table_expr.name

    predicates: list[exp.Expression] = []
    enforced: dict[str, dict[str, list[str]]] = {}

    for table_name, cols in required.items():
        if table_name not in used_tables:
            continue

        qualifier = table_alias.get(table_name, table_name)
        for col_name, rule in cols.items():
            values = rule.get("values")
            if not values:
                continue

            value_list = [str(v).strip() for v in values]
            in_expr = exp.In(
                this=exp.column(col_name, table=qualifier),
                expressions=[_literal(v) for v in value_list],
            )
            predicates.append(in_expr)
            enforced.setdefault(table_name, {})[col_name] = value_list

    if predicates:
        combined_predicate = predicates[0]
        for pred in predicates[1:]:
            combined_predicate = exp.and_(combined_predicate, pred)

        where_clause = tree.args.get("where")
        if where_clause is None:
            tree.set("where", exp.Where(this=combined_predicate))
        else:
            tree.set(
                "where", exp.Where(this=exp.and_(where_clause.this, combined_predicate))
            )

    return tree.sql(dialect="tsql"), enforced
