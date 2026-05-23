"""
SQL Refiner — optional SQLCoder-based refinement step.
Drop-in module: enable by passing a BaseLLM, disable by passing None.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.agent.llm.base import BaseLLM

logger = logging.getLogger(__name__)


def _build_create_table_block(schemas: list[dict]) -> str:
    parts = []
    for s in schemas:
        schema_name = s.get("schema_name", "dbo")
        table_name = s.get("table_name", "")
        columns = []

        for col in s.get("columns", []):
            if isinstance(col, dict):
                col_name = col.get("name", "col")
                col_type = col.get("type", "VARCHAR(255)")
                pk = " PRIMARY KEY" if col.get("is_primary_key") else ""
                nullable = "" if col.get("nullable", True) else " NOT NULL"
                columns.append(f"    {col_name} {col_type}{pk}{nullable}")
            elif isinstance(col, str):
                columns.append(f"    {col}")

        # fallback: parse from document string
        if not columns:
            document = s.get("document", "")
            for line in document.splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    col_name = stripped[2:].split()[0]
                    columns.append(f"    {col_name}")

        cols_str = ",\n".join(columns) if columns else "    id INT"
        parts.append(f"CREATE TABLE {schema_name}.{table_name} (\n{cols_str}\n);")

    return "\n\n".join(parts)


def refine_sql(
    sql: str,
    schemas: list[dict],
    sqlcoder_llm: Optional[BaseLLM],
    hallucinated_tables: list[str] | None = None,
    hallucinated_cols: list[str] | None = None,
    validation_errors: list[str] | None = None,
) -> tuple[str, bool]:
    """
    Attempt to fix SQL using SQLCoder.

    Returns:
        (refined_sql, was_refined)
        - was_refined=True  → SQLCoder ran and returned something
        - was_refined=False → SQLCoder disabled or failed, original SQL returned

    Usage:
        # Enable
        sql, refined = refine_sql(sql, schemas, sqlcoder_llm=llm_sqlcoder)

        # Disable — just pass None, zero impact on pipeline
        sql, refined = refine_sql(sql, schemas, sqlcoder_llm=None)
    """

    # ── Disabled ──────────────────────────────────────────────────────────────
    if sqlcoder_llm is None:
        logger.debug("SQLCoder refiner disabled (sqlcoder_llm=None), skipping")
        return sql, False

    # ── Build issues block ────────────────────────────────────────────────────
    issues_lines = []
    if hallucinated_tables:
        issues_lines.append(
            f"These tables do NOT exist, remove or replace them:\n"
            + "\n".join(f"  ✗ {t}" for t in hallucinated_tables)
        )
    if hallucinated_cols:
        issues_lines.append(
            f"These columns do NOT exist, find the real column from schema:\n"
            + "\n".join(f"  ✗ {c}" for c in hallucinated_cols)
        )
    if validation_errors:
        issues_lines.append(
            f"Validation errors to fix:\n"
            + "\n".join(f"  ✗ {e}" for e in validation_errors)
        )

    issues_block = (
        "\n\n".join(issues_lines) if issues_lines else "General SQL fix needed."
    )

    schema_block = _build_create_table_block(schemas)

    prompt = f"""### Task
Fix the following SQL query using only the tables and columns in the schema below.

### Issues Found
{issues_block}

### Broken SQL
{sql}

### Database Schema
{schema_block}

### Fixed SQL
```sql
"""

    try:
        result = sqlcoder_llm.generate(system_prompt="", user_prompt=prompt)
        refined = result.replace("```sql", "").replace("```", "").strip()

        if not refined:
            logger.warning("SQLCoder returned empty result")
            return sql, False

        logger.info(f"SQLCoder refined SQL (first 120): {refined[:120]}")
        return refined, True

    except Exception as e:
        logger.error(f"SQLCoder refiner failed: {e}")
        return sql, False
