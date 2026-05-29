from __future__ import annotations

from collections import defaultdict
import json
import logging
from typing import Any, Dict

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)

# Maximum number of RBAC-driven retries before hard-denying to prevent
# infinite loops when the generator keeps producing the same SQL.
MAX_RBAC_RETRIES = 2


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalize_table_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    return name.split(".")[-1].lower()


def _allowed_table_set(allowed_tables: list[str]) -> set[str]:
    return {_normalize_table_name(t) for t in allowed_tables if str(t).strip()}


def _normalize_mandatory_filters(
    mandatory_filters: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """
    Normalize mandatory_filters to:
      {table_bare_lower: {column_lower: {"filter": ..., "values": [...]}}}
    """
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for table, filters in (mandatory_filters or {}).items():
        table_key = _normalize_table_name(table)
        if not table_key or not isinstance(filters, dict):
            continue

        col_map: dict[str, dict[str, Any]] = {}
        for col, rule in filters.items():
            if not col:
                continue
            if isinstance(rule, dict):
                ftype = str(rule.get("filter", "id"))
                vals = rule.get("values")
            else:
                ftype = "id"
                vals = None

            if vals is not None and not isinstance(vals, list):
                vals = [vals]

            col_map[str(col).lower()] = {"filter": ftype, "values": vals}

        out[table_key] = col_map
    return out


# ---------------------------------------------------------------------------
# SQL context extraction  (single parse — result shared with _check_sql_rbac)
# ---------------------------------------------------------------------------


def _extract_sql_context(
    sql: str,
) -> tuple[set[str], dict[str, str], dict[tuple[str, str], list[str]]]:
    """
    Parse SQL once and extract:
      - used_tables   : set of bare table names
      - alias_to_table: table-alias -> bare table name
      - filter_values : (bare_table, column) -> list of literal values in WHERE

    SELECT-list column aliases are resolved back to their real column names
    before being recorded in filter_values, preventing alias-based bypasses
    of mandatory filter checks.
    """
    tree = sqlglot.parse_one(sql, dialect="tsql")

    used_tables: set[str] = set()
    alias_to_table: dict[str, str] = {}

    for t in tree.find_all(exp.Table):
        bare = _normalize_table_name(t.name or "")
        if not bare:
            continue
        used_tables.add(bare)
        alias = (t.alias_or_name or "").strip().lower()
        if alias:
            alias_to_table[alias] = bare

    # Build SELECT-list column alias map: alias_name -> real_column_name
    # Prevents "SELECT user_id AS org_id … WHERE org_id = X" from
    # satisfying the mandatory filter on 'org_id' while leaving
    # 'user_id' entirely unfiltered.
    col_alias_map: dict[str, str] = {}
    for alias_node in tree.find_all(exp.Alias):
        real = alias_node.args.get("this")
        alias_name = (alias_node.alias or "").strip().lower()
        if isinstance(real, exp.Column) and alias_name:
            col_alias_map[alias_name] = (real.name or "").lower()

    def resolve_table_for_col(col: exp.Column) -> str:
        table_ref_expr = col.args.get("table")
        table_ref = (table_ref_expr.name if table_ref_expr else "").lower()
        if table_ref:
            if table_ref in alias_to_table:
                return alias_to_table[table_ref]
            return _normalize_table_name(table_ref)
        # Unqualified column: attribute to the sole table, else ambiguous.
        if len(used_tables) == 1:
            return next(iter(used_tables))
        return ""

    filter_values: dict[tuple[str, str], list[str]] = defaultdict(list)

    # Equality predicates: col = <literal>
    for eq_node in tree.find_all(exp.EQ):
        left = eq_node.args.get("this")
        right = eq_node.args.get("expression")
        if not isinstance(left, exp.Column) or not isinstance(right, exp.Literal):
            continue
        table_name = resolve_table_for_col(left)
        col_name = col_alias_map.get(
            (left.name or "").lower(), (left.name or "").lower()
        )
        if not table_name or not col_name:
            continue
        filter_values[(table_name, col_name)].append(str(right.this))

    # IN predicates: col IN (...)
    for in_node in tree.find_all(exp.In):
        left = in_node.args.get("this")
        if not isinstance(left, exp.Column):
            continue
        table_name = resolve_table_for_col(left)
        col_name = col_alias_map.get(
            (left.name or "").lower(), (left.name or "").lower()
        )
        if not table_name or not col_name:
            continue
        for item in in_node.args.get("expressions") or []:
            if isinstance(item, exp.Literal):
                filter_values[(table_name, col_name)].append(str(item.this))

    return used_tables, alias_to_table, filter_values


# ---------------------------------------------------------------------------
# RBAC check  (accepts pre-parsed context — no second SQL parse)
# ---------------------------------------------------------------------------


def _check_sql_rbac(
    used_tables: set[str],
    filter_values: dict[tuple[str, str], list[str]],
    allowed_tables: list[str],
    mandatory_filters: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], list[str]]:
    """
    Accepts pre-parsed SQL context so the SQL is never parsed twice.

    Returns:
      - unauthorized_table_violations
      - missing_filter_violations
      - value_mismatch_violations
    """
    unauthorized: list[str] = []
    missing_filters: list[str] = []
    mismatched_values: list[str] = []

    allowed_set = _allowed_table_set(allowed_tables)
    required = _normalize_mandatory_filters(mandatory_filters)

    if allowed_set:
        for table_name in sorted(used_tables):
            if table_name not in allowed_set:
                unauthorized.append(f"Disallowed table referenced: {table_name}")

    for table_name, table_filters in required.items():
        if table_name not in used_tables:
            continue

        for col_name, rule in table_filters.items():
            filter_type = str(rule.get("filter", "id"))
            if filter_type not in ("id", "enum"):
                continue

            seen_vals = filter_values.get((table_name, col_name), [])
            if not seen_vals:
                missing_filters.append(
                    f"Table '{table_name}' is used but missing mandatory filter on '{col_name}'."
                )
                continue

            allowed_vals = rule.get("values")
            if allowed_vals:
                allowed_norm = {str(v).strip() for v in allowed_vals}
                for val in seen_vals:
                    if str(val).strip() not in allowed_norm:
                        mismatched_values.append(
                            f"Filter value mismatch for {table_name}.{col_name}."
                        )
                        break

    return unauthorized, missing_filters, mismatched_values


# ---------------------------------------------------------------------------
# Authorization policy builder
# ---------------------------------------------------------------------------


def _build_authorization_policy(
    mandatory_filters: dict[str, Any],
    used_tables: set[str],
) -> dict[str, Any]:
    """
    Build a structured authorization policy containing only the tables
    actually referenced by the query and only columns with concrete values.
    Empty policy -> {"priority": "hard_constraint", "tables": {}}.
    """
    normalized = _normalize_mandatory_filters(mandatory_filters)
    tables: dict[str, Any] = {}
    for table, cols in normalized.items():
        if table not in used_tables:
            continue
        col_map: dict[str, Any] = {}
        for col, rule in cols.items():
            if rule.get("values"):
                col_map[col] = {
                    "values": rule["values"],
                    "filter_type": rule["filter"],
                }
        if col_map:
            tables[table] = col_map
    return {"priority": "hard_constraint", "tables": tables}


# ---------------------------------------------------------------------------
# Shared hard-deny helper
# ---------------------------------------------------------------------------


def _hard_deny(state: Dict[str, Any], violations: list[str]) -> Dict[str, Any]:
    """
    Return a hard-deny state. Internal violation details are logged but never
    surfaced to the end user.
    """
    logger.warning("RBAC enforcer: access denied: %s", violations)
    return {
        **state,
        "rbac_denied": True,
        "permission_denied": True,
        "validation_passed": False,
        "rbac_enforced_filters": {},
        "authorization_policy": {},
        "validation_result": {
            "needs_retry": False,
            "logical_ok": False,
            "errors": ["Access policy violation"],
            "reasoning": "RBAC authorization failed.",
        },
        "validation_errors": ["RBAC denied"],
        # Never expose internal policy values to end users.
        "user_facing_response": (
            "Sorry, we cannot proceed with this request because it may not "
            "be authorized for your access level."
        ),
    }


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def rbac_enforcer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node: enforce RBAC after SQL generation.

    Decision tree
    ─────────────
    1. No SQL in state          → pass through (nothing to check).
    2. Parse error              → safe retry (not a silent pass).
    3. Unauthorized table or
       value mismatch           → hard deny, no retry.
    4. Retry limit exceeded     → hard deny (prevents infinite loop when the
                                  generator keeps producing the same SQL).
    5. Missing mandatory filter → forward authorization_policy, request retry.
    6. Policy present, all
       values verified          → forward authorization_policy, request retry
                                  so the validator/generator can hardcode values.
    7. No policy needed         → validation passed, graph continues.
    """
    sql = state.get("generated_sql", "") or ""
    mandatory_filters = state.get("mandatory_filters", {}) or {}
    allowed_tables = state.get("allowed_tables", []) or []
    retry_count = state.get("retry_count", 0)

    # ── 1. No SQL ────────────────────────────────────────────────────────────
    if not sql:
        return {
            **state,
            "rbac_denied": False,
            "permission_denied": False,
            "rbac_enforced_filters": {},
            "authorization_policy": {},
        }

    # ── 2. Parse + check (single SQL parse shared across both functions) ─────
    # used_tables initialised here so it is always bound even if the try fails.
    used_tables: set[str] = set()
    try:
        used_tables, _alias_map, filter_values = _extract_sql_context(sql)
        unauthorized, missing_filters, mismatched_values = _check_sql_rbac(
            used_tables, filter_values, allowed_tables, mandatory_filters
        )
    except Exception as exc:
        # Parse failure is not a silent pass — ask for a retry so the
        # generator can produce parseable SQL rather than sneaking through.
        logger.warning("RBAC SQL check failed: %s", exc)
        return {
            **state,
            "rbac_denied": False,
            "permission_denied": False,
            "validation_passed": False,
            "rbac_enforced_filters": {},
            "authorization_policy": {},
            "validation_result": {
                "needs_retry": True,
                "logical_ok": False,
                "errors": [f"RBAC parse error: {exc}"],
                "reasoning": "SQL could not be parsed for RBAC validation.",
            },
            "validation_errors": [f"RBAC parse error: {exc}"],
            "retry_feedback": {
                "issues": ["rbac_parse_error"],
                "reasoning": f"SQL failed RBAC parse: {exc}",
                "failed_sql": sql,
                "attempt": retry_count + 1,
            },
        }

    # ── 3. Hard deny — disallowed tables or value mismatch ───────────────────
    if unauthorized or mismatched_values:
        return _hard_deny(state, unauthorized + mismatched_values)

    # ── 4. Retry limit guard ─────────────────────────────────────────────────
    # If we have already retried MAX_RBAC_RETRIES times and the generator
    # still hasn't embedded the required filters, hard-deny rather than loop.
    if retry_count >= MAX_RBAC_RETRIES and (
        missing_filters
        or _build_authorization_policy(mandatory_filters, used_tables)["tables"]
    ):
        logger.warning(
            "RBAC enforcer: retry limit (%d) exceeded — hard denying.", MAX_RBAC_RETRIES
        )
        return _hard_deny(state, ["RBAC retry limit exceeded"])

    # Build policy once — shared by branches 5 and 6.
    authorization_policy = _build_authorization_policy(mandatory_filters, used_tables)

    # ── 5. Missing mandatory filters → retry with policy ─────────────────────
    if missing_filters:
        logger.info("RBAC enforcer: missing mandatory filters: %s", missing_filters)
        return {
            **state,
            "rbac_denied": False,
            "permission_denied": False,
            "validation_passed": False,
            "rbac_enforced_filters": {},
            "authorization_policy": authorization_policy,
            "validation_result": {
                "needs_retry": True,
                "logical_ok": False,
                "errors": missing_filters,
                "reasoning": "Mandatory RBAC filters missing — validator must inject them.",
            },
            "validation_errors": missing_filters,
            "retry_feedback": {
                "issues": ["missing_mandatory_filters"],
                "reasoning": "Query used restricted tables without required filters.",
                "failed_sql": sql,
                "authorization_policy": authorization_policy,
                "attempt": retry_count + 1,
            },
        }

    # ── 6. Policy present — check if already hardcoded ──────────────────────
    if authorization_policy["tables"]:

        # Check whether every required value is already present in the SQL
        already_satisfied = True
        unsatisfied = []

        for table, cols in authorization_policy["tables"].items():
            for col, rule in cols.items():
                seen = filter_values.get((table, col), [])
                required_vals = {str(v).strip() for v in (rule.get("values") or [])}
                seen_norm = {str(v).strip() for v in seen}

                if not required_vals.issubset(seen_norm):
                    already_satisfied = False
                    unsatisfied.append(f"{table}.{col}")

        if already_satisfied:
            # SQL already has the correct hardcoded filters → pass
            logger.info("RBAC enforcer: all policy filters already present in SQL.")
            return {
                **state,
                "rbac_denied": False,
                "permission_denied": False,
                "validation_passed": True,
                "rbac_enforced_filters": authorization_policy["tables"],
                "authorization_policy": authorization_policy,
                "validation_result": {
                    "needs_retry": False,
                    "logical_ok": True,
                    "errors": [],
                    "reasoning": "RBAC policy already satisfied in SQL.",
                },
                "retry_feedback": None,
            }

        # Values missing from SQL → retry
        logger.info("RBAC enforcer: policy filters not yet hardcoded: %s", unsatisfied)
        return {
            **state,
            "rbac_denied": False,
            "permission_denied": False,
            "validation_passed": False,
            "rbac_enforced_filters": {},
            "authorization_policy": authorization_policy,
            "validation_result": {
                "needs_retry": True,
                "logical_ok": True,
                "errors": [],
                "reasoning": "SQL structurally valid — validator must hardcode mandatory RBAC filters.",
            },
            "retry_feedback": {
                "issues": ["authorization_policy_pending"],
                "reasoning": "Validator must rewrite query applying authorization_policy.",
                "failed_sql": sql,
                "authorization_policy": authorization_policy,
                "attempt": retry_count + 1,
            },
        }

    # ── 7. No policy needed → pass ───────────────────────────────────────────
    return {
        **state,
        "rbac_denied": False,
        "permission_denied": False,
        "validation_passed": True,
        "rbac_enforced_filters": {},
        "authorization_policy": {},
    }
