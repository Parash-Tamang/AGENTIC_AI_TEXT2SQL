"""Filter extraction utility for confirmed SQL queries using real SQLGlot.

Extracts WHERE clause conditions from validated SQL into structured dict format.
Called by sql_post_execution_validator_node when validation_passed = True.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)


def extract_filters_from_sql(sql: str, dialect: str = "tsql") -> Dict[str, Any]:
    """Extract WHERE clause conditions from SQL into structured dict.

    Args:
        sql: SQL query string to parse
        dialect: SQL dialect (default: "tsql" for SQL Server)

    Returns:
        Dictionary mapping column/condition names to their values/operators.
        Returns empty dict if no WHERE clause or parsing fails.

    Examples:
        >>> extract_filters_from_sql("SELECT * FROM users WHERE age > 18 AND active = true")
        {
            'age': [{'operator': '>', 'value': 18, 'raw': 'age > 18'}],
            'active': [{'operator': '=', 'value': True, 'raw': 'active = true'}]
        }

        >>> extract_filters_from_sql("SELECT * FROM orders WHERE status IN ('pending', 'approved')")
        {
            'status': [{'operator': 'IN', 'value': ['pending', 'approved'], 'raw': "status IN ('pending', 'approved')"}]
        }
    """
    filters: Dict[str, Any] = {}

    try:
        # Parse SQL using real SQLGlot
        parsed = sqlglot.parse_one(sql, read=dialect)
        if not isinstance(parsed, exp.Select):
            logger.warning("Parsed SQL is not a SELECT statement")
            return filters

        where_clause = parsed.find(exp.Where)
        if not where_clause:
            logger.debug("No WHERE clause found in SQL")
            return filters

        # Extract conditions from WHERE
        _parse_conditions(where_clause.this, filters)

    except Exception as exc:
        logger.warning("Failed to extract filters from SQL: %s", exc)

    return filters


def _parse_conditions(
    expr: exp.Expression,
    filters: Dict[str, Any],
    parent_op: Optional[str] = None,
) -> None:
    """Recursively parse WHERE conditions into filters dict.

    Handles:
    - Simple comparisons: col = value, col > value, etc.
    - IN clauses: col IN (val1, val2, ...)
    - AND/OR combinations
    - BETWEEN clauses
    - IS NULL / IS NOT NULL
    - Nested expressions
    """
    if isinstance(expr, exp.And):
        # AND: collect both sides
        _parse_conditions(expr.left, filters, "AND")
        _parse_conditions(expr.right, filters, "AND")

    elif isinstance(expr, exp.Or):
        # OR: collect both sides
        _parse_conditions(expr.left, filters, "OR")
        _parse_conditions(expr.right, filters, "OR")

    elif isinstance(expr, (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)):
        # Comparison operators
        _extract_comparison(expr, filters)

    elif isinstance(expr, exp.In):
        # IN clause
        _extract_in(expr, filters)

    elif isinstance(expr, exp.Between):
        # BETWEEN clause
        _extract_between(expr, filters)

    elif isinstance(expr, (exp.Is, exp.IsNot)):
        # IS NULL, IS NOT NULL
        _extract_is_null(expr, filters)


def _extract_comparison(expr: exp.Expression, filters: Dict[str, Any]) -> None:
    """Extract comparison: col op value."""
    left = expr.left
    right = expr.right
    op_map = {
        exp.EQ: "=",
        exp.NEQ: "!=",
        exp.GT: ">",
        exp.GTE: ">=",
        exp.LT: "<",
        exp.LTE: "<=",
    }
    op = op_map.get(type(expr), "=")

    # Left side should be column
    col_name = _extract_column_name(left)
    if not col_name:
        return

    # Right side is the value
    value = _extract_value(right)

    if col_name not in filters:
        filters[col_name] = []

    filters[col_name].append(
        {
            "operator": op,
            "value": value,
            "raw": expr.sql(),
        }
    )


def _extract_in(expr: exp.In, filters: Dict[str, Any]) -> None:
    """Extract IN clause: col IN (val1, val2, ...)."""
    col_name = _extract_column_name(expr.this)
    if not col_name:
        return

    values = []
    if hasattr(expr, "expressions") and expr.expressions:
        for val_expr in expr.expressions:
            val = _extract_value(val_expr)
            if val is not None:
                values.append(val)

    if col_name not in filters:
        filters[col_name] = []

    filters[col_name].append(
        {
            "operator": "IN",
            "value": values,
            "raw": expr.sql(),
        }
    )


def _extract_between(expr: exp.Between, filters: Dict[str, Any]) -> None:
    """Extract BETWEEN clause: col BETWEEN val1 AND val2."""
    col_name = _extract_column_name(expr.this)
    if not col_name:
        return

    low = _extract_value(expr.args.get("low"))
    high = _extract_value(expr.args.get("high"))

    if col_name not in filters:
        filters[col_name] = []

    filters[col_name].append(
        {
            "operator": "BETWEEN",
            "value": {"low": low, "high": high},
            "raw": expr.sql(),
        }
    )


def _extract_is_null(expr: exp.Expression, filters: Dict[str, Any]) -> None:
    """Extract IS NULL / IS NOT NULL."""
    col_name = _extract_column_name(expr.this)
    if not col_name:
        return

    op = "IS NOT NULL" if isinstance(expr, exp.IsNot) else "IS NULL"

    if col_name not in filters:
        filters[col_name] = []

    filters[col_name].append(
        {
            "operator": op,
            "value": None,
            "raw": expr.sql(),
        }
    )


def _extract_column_name(expr: exp.Expression) -> Optional[str]:
    """Extract column name from expression."""
    if isinstance(expr, exp.Column):
        # Return just the column name (not table.column)
        return expr.name

    if isinstance(expr, exp.Identifier):
        return expr.name

    return None


def _extract_value(expr: exp.Expression) -> Any:
    """Extract literal value from expression."""
    if isinstance(expr, exp.Literal):
        val = expr.this
        # Parse based on type
        if expr.is_int:
            try:
                return int(val)
            except (ValueError, TypeError):
                return val
        if expr.is_number:
            try:
                return float(val)
            except (ValueError, TypeError):
                return val
        if expr.is_string:
            return str(val)
        return val

    if isinstance(expr, exp.Boolean):
        return expr.this.lower() == "true"

    if isinstance(expr, exp.Null):
        return None

    # Fallback: return SQL representation
    return expr.sql()


def flatten_filters(filters: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Flatten filters dict (possibly containing _or groups) into flat list.

    Converts the structured filter output into a simple list for prompt injection.
    Handles both flat AND conditions and nested OR groups.

    Args:
        filters: Filter dict from extract_filters_from_sql, possibly with _or key

    Returns:
        List of filter dicts with "column", "operator", "value", "group" keys.
        Items with group="and" are flat conditions.
        Items with group="or_N" belong to same OR group (all have same N).

    Example:
        Input:
        {
            "store_id": [{"operator": "=", "value": 5}],
            "_or": [
                {"category": [{"operator": "=", "value": "vest"}]},
                {"category": [{"operator": "=", "value": "pants"}]}
            ]
        }

        Output:
        [
            {"column": "store_id", "operator": "=", "value": 5, "group": "and"},
            {"column": "category", "operator": "=", "value": "vest", "group": "or_0"},
            {"column": "category", "operator": "=", "value": "pants", "group": "or_0"}
        ]
    """
    flattened: list[Dict[str, Any]] = []

    if not filters or not isinstance(filters, dict):
        return flattened

    # Process flat AND conditions (everything except _or key)
    for col_name, col_filters in filters.items():
        if col_name == "_or":
            continue

        if not isinstance(col_filters, list):
            continue

        for filter_item in col_filters:
            if not isinstance(filter_item, dict):
                continue

            flattened.append(
                {
                    "column": col_name,
                    "operator": filter_item.get("operator", "="),
                    "value": filter_item.get("value"),
                    "raw": filter_item.get("raw", ""),
                    "group": "and",
                }
            )

    # Process OR groups - all items in _or list share the same group ID
    or_groups = filters.get("_or", [])
    if isinstance(or_groups, list) and or_groups:
        # All items from _or list belong to the same group
        for or_group in or_groups:
            if not isinstance(or_group, dict):
                continue

            for col_name, col_filters in or_group.items():
                if not isinstance(col_filters, list):
                    continue

                for filter_item in col_filters:
                    if not isinstance(filter_item, dict):
                        continue

                    flattened.append(
                        {
                            "column": col_name,
                            "operator": filter_item.get("operator", "="),
                            "value": filter_item.get("value"),
                            "raw": filter_item.get("raw", ""),
                            "group": "or_0",  # All _or items share group "or_0"
                        }
                    )

    return flattened


def filter_has_column(filters: Dict[str, Any], column_name: str) -> bool:
    """Check if a column filter exists in filters (including _or branches).

    Args:
        filters: Filter dict from extract_filters_from_sql
        column_name: Column name to search for

    Returns:
        True if column exists in flat conditions or any _or group
    """
    if not filters or not isinstance(filters, dict):
        return False

    col_lower = column_name.lower()

    # Check flat conditions
    for col in filters.keys():
        if col != "_or" and col.lower() == col_lower:
            return True

    # Check OR groups
    or_groups = filters.get("_or", [])
    if isinstance(or_groups, list):
        for or_group in or_groups:
            if isinstance(or_group, dict):
                for col in or_group.keys():
                    if col.lower() == col_lower:
                        return True

    return False


# ============================================================================
# RBAC Permission Validation (uses permissions.json)
# ============================================================================

import json
from pathlib import Path


class PermissionValidator:
    """Validates extracted filters against role-based access control rules.

    Uses permissions.json to enforce:
    - Table-level access for roles
    - Required filter columns (id, enum types)
    - Allowed filter values (for enum filters)

    Example:
        validator = PermissionValidator()
        is_allowed = validator.validate_access(
            role="customer",
            table="SalesLT.Customer",
            filters={"CustomerID": [{"operator": "=", "value": 42}]}
        )
    """

    def __init__(self, permissions_path: Optional[str] = None):
        """Initialize with permissions JSON file path.

        Args:
            permissions_path: Path to permissions.json. If None, searches for it
                            in common locations (repo root, src/, etc).
        """
        self.permissions_path = self._find_permissions_file(permissions_path)
        self.permissions = self._load_permissions()
        logger.info("✅ PermissionValidator initialized with %s", self.permissions_path)

    def _find_permissions_file(self, explicit_path: Optional[str] = None) -> str:
        """Find permissions.json in common locations."""
        if explicit_path and Path(explicit_path).exists():
            return explicit_path

        search_paths = [
            Path.cwd() / "permissions.json",  # Current directory
            Path(__file__).parent.parent.parent / "permissions.json",  # Repo root
            Path(__file__).parent.parent / "permissions.json",  # src/
        ]

        for path in search_paths:
            if path.exists():
                logger.info("Found permissions.json at: %s", path)
                return str(path)

        raise FileNotFoundError(
            "permissions.json not found. Please ensure it exists in repo root or src/"
        )

    def _load_permissions(self) -> Dict[str, Any]:
        """Load and parse permissions.json."""
        try:
            with open(self.permissions_path, "r") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to load permissions.json: %s", exc)
            raise

    def validate_access(
        self,
        role: str,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate if role can access table with given filters.

        Args:
            role: Role name (e.g., "customer", "sales", "admin")
            table: Table name (e.g., "SalesLT.Customer")
            filters: Extracted filters dict from extract_filters_from_sql()

        Returns:
            {
                "allowed": bool,
                "reason": str,
                "required_filters": list,
                "missing_filters": list,
                "invalid_values": list,
                "access_level": str  # "unrestricted" or "filtered"
            }
        """
        result = {
            "allowed": False,
            "reason": "",
            "required_filters": [],
            "missing_filters": [],
            "invalid_values": [],
            "access_level": None,
        }

        # Check if role exists
        if role not in self.permissions.get("permissions", {}):
            result["reason"] = f"Role '{role}' not found in permissions"
            return result

        role_perms = self.permissions["permissions"][role]

        # Check if table is accessible to role
        if table not in role_perms:
            result["reason"] = f"Role '{role}' has no access to table '{table}'"
            return result

        table_config = role_perms[table]
        access_level = table_config.get("access_level", "unrestricted")
        result["access_level"] = access_level

        # If unrestricted, no filter validation needed
        if access_level == "unrestricted":
            result["allowed"] = True
            result["reason"] = f"Role '{role}' has unrestricted access to '{table}'"
            return result

        # Filtered access: validate required filters
        required = table_config.get("required_filters", [])
        result["required_filters"] = [f["column"] for f in required]

        filters = filters or {}
        missing = []
        invalid = []

        for req_filter in required:
            col_name = req_filter["column"]
            filter_type = req_filter.get("filter_type", "id")
            allowed_values = req_filter.get("values")

            # Check if required column is present in filters
            if col_name not in filters:
                missing.append(col_name)
                continue

            # Validate filter values (for enum filters)
            if filter_type == "enum" and allowed_values:
                col_filters = filters.get(col_name, [])
                for f in col_filters:
                    val = f.get("value")
                    if isinstance(val, list):
                        # IN clause: check all values
                        for v in val:
                            if str(v) not in [str(av) for av in allowed_values]:
                                invalid.append(
                                    {
                                        "column": col_name,
                                        "value": v,
                                        "reason": f"Value not in allowed: {allowed_values}",
                                    }
                                )
                            print(val)
                    else:
                        # Single value
                        if str(val) not in [str(av) for av in allowed_values]:
                            invalid.append(
                                {
                                    "column": col_name,
                                    "value": val,
                                    "reason": f"Value not in allowed: {allowed_values}",
                                }
                            )
        print(f.get("value"))
        result["missing_filters"] = missing
        result["invalid_values"] = invalid
        result["allowed"] = len(missing) == 0 and len(invalid) == 0

        if result["allowed"]:
            result["reason"] = (
                f"✅ Role '{role}' can access '{table}' with valid filters"
            )
        else:
            if missing:
                result["reason"] = f"❌ Missing required filters: {missing}"
            if invalid:
                result["reason"] = (
                    f"❌ Invalid filter values: {[i['column'] for i in invalid]}"
                )

        return result

    def validate_sql_access(
        self,
        role: str,
        sql: str,
        table: str,
        dialect: str = "tsql",
    ) -> Dict[str, Any]:
        """Extract filters from SQL and validate access in one call.

        Args:
            role: Role name
            sql: SQL query string
            table: Table being queried
            dialect: SQL dialect

        Returns:
            Same format as validate_access()
        """
        filters = extract_filters_from_sql(sql, dialect=dialect)
        return self.validate_access(role=role, table=table, filters=filters)


def enforce_rbac(
    role: str,
    table: str,
    filters: Dict[str, Any],
    permissions_path: Optional[str] = None,
) -> tuple[bool, str]:
    """Convenience function: validate access and return (allowed, reason).

    Args:
        role: Role name
        table: Table name
        filters: Extracted filters
        permissions_path: Optional path to permissions.json

    Returns:
        (allowed: bool, reason: str)

    Example:
        allowed, reason = enforce_rbac(
            role="customer",
            table="SalesLT.Customer",
            filters=extracted_filters
        )
        if not allowed:
            raise PermissionError(reason)
    """
    try:
        validator = PermissionValidator(permissions_path)
        result = validator.validate_access(role, table, filters)
        return result["allowed"], result["reason"]
    except Exception as exc:
        logger.error("RBAC validation error: %s", exc)
        return False, f"RBAC check failed: {exc}"


__all__ = [
    "extract_filters_from_sql",
    "flatten_filters",
    "filter_has_column",
    "PermissionValidator",
    "enforce_rbac",
]
