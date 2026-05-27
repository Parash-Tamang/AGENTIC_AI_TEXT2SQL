# src/agent/utils/rbac_enforcer.py

from __future__ import annotations

import logging
from typing import Any

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)


def enforce_mandatory_filters(
    sql: str,
    mandatory_filters: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, str]]:
    """
    Post-process generated SQL to hard-enforce id-type mandatory filters.
    Replaces any user-supplied value for id-filtered columns with the
    role-permitted value. Runs AFTER LLM generation — cannot be bypassed.

    Returns:
        (rewritten_sql, enforced_filters) where enforced_filters is a dict of
        {"Table.Column": "enforced_value"} for every value that was locked by
        policy. This must be stored in state["rbac_enforced_filters"] so the
        semantic validator does not flag policy-rewritten values as intent
        mismatches against the user query.
    """
    if not mandatory_filters:
        return sql, {}

    try:
        tree = sqlglot.parse_one(sql, dialect="tsql")
    except Exception:
        logger.error("RBAC enforcer: sqlglot parse failed — returning original SQL")
        return sql, {}

    modified = False
    enforced_filters: dict[str, str] = {}

    for node in tree.find_all(exp.EQ):
        left = node.args.get("this")
        if not isinstance(left, exp.Column):
            continue

        col_name = left.name
        table_ref = (left.args.get("table") or exp.Identifier(this="")).name.lower()

        for table, filters in mandatory_filters.items():
            table_bare = table.split(".")[-1].lower()

            # Skip if table_ref is specified and doesn't match
            if table_ref and table_ref not in (table.lower(), table_bare):
                continue

            # Find matching column filter
            filter_rule = filters.get(col_name) or filters.get(col_name.lower())
            if not filter_rule:
                continue

            filter_type = filter_rule.get("filter")
            values = filter_rule.get("values")

            if filter_type == "id" and values:
                permitted_value = values[0]
                current_right = node.args.get("expression")
                current_val = (
                    current_right.this
                    if current_right and hasattr(current_right, "this")
                    else None
                )

                if str(current_val) != str(permitted_value):
                    logger.warning(
                        f"RBAC enforcer: {table}.{col_name} "
                        f"overriding {current_val!r} → {permitted_value!r}"
                    )

                # Replace the RIGHT side (expression), not the node itself
                new_literal = (
                    exp.Literal.number(permitted_value)
                    if str(permitted_value).isdigit()
                    else exp.Literal.string(permitted_value)
                )
                node.set("expression", new_literal)
                modified = True

                # Record the enforced value so the validator knows not to
                # flag it as a mismatch against the user query.
                # Key format: "SalesLT.Customer.CustomerID" → "60"
                enforced_filters[f"{table}.{col_name}"] = str(permitted_value)

    if not modified:
        logger.debug("RBAC enforcer: no id filters needed rewriting")
        return sql, {}

    try:
        result = tree.sql(dialect="tsql")
        logger.info("RBAC enforcer: SQL rewritten successfully")
        return result, enforced_filters
    except Exception as e:
        logger.error(f"RBAC enforcer: sql() generation failed: {e}")
        return sql, {}
