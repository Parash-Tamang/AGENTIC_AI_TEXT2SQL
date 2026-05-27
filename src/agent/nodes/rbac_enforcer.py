from __future__ import annotations

from typing import Any, Dict
import logging

from src.agent.utils.rbac_enforcer import enforce_mandatory_filters
from src.agent.nodes.sql_validator import _check_rbac_violations

logger = logging.getLogger(__name__)


def rbac_enforcer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node: enforce RBAC post-validation.

    Behavior:
      - If role's allowed_tables excludes any table referenced in SQL, mark
        `rbac_denied` and set validation_errors (non-retryable).
      - Otherwise, rewrite id-type mandatory filters to permitted values and
        record them in `rbac_enforced_filters`.
    """
    sql = state.get("generated_sql", "") or ""
    mandatory_filters = state.get("mandatory_filters", {}) or {}
    allowed_tables = state.get("allowed_tables", []) or []

    # Quick early-return when there's nothing to do
    if not sql:
        return {**state, "rbac_denied": False, "rbac_enforced_filters": {}}

    # Deny if SQL references disallowed tables
    if allowed_tables:
        violations = _check_rbac_violations(sql, allowed_tables, mandatory_filters)
        if violations:
            logger.warning(f"RBAC enforcer: access denied: {violations}")
            return {
                **state,
                "rbac_denied": True,
                "validation_passed": False,
                "validation_errors": [f"RBAC denied: {'; '.join(violations)}"],
            }

    # Otherwise, rewrite id filters and record enforced values
    try:
        rewritten_sql, enforced_filters = enforce_mandatory_filters(
            sql, mandatory_filters
        )
    except Exception as exc:
        logger.warning(f"RBAC enforcer failed: {exc}")
        return {**state, "rbac_denied": False, "rbac_enforced_filters": {}}

    return {
        **state,
        "generated_sql": rewritten_sql,
        "rbac_denied": False,
        "rbac_enforced_filters": enforced_filters or {},
    }
