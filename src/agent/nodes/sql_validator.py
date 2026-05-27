from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlglot
import sqlglot.expressions as exp
from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM
from src.agent.utils.pretty_print import pretty_log
from src.agent.nodes.sql_results_validator import (
    _format_schemas_for_llm,
    _format_join_paths_for_llm,
)
from src.agent.prompt.sql_validator import SQL_VALIDATION_SYSTEM

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
SQL_VALIDATION_LOG = LOG_DIR / "sql_validation.jsonl"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StructuralValidationResult(BaseModel):
    syntax_valid: bool = True
    syntax_error: str = ""
    missing_tables: list[str] = Field(default_factory=list)
    missing_columns: list[dict[str, str]] = Field(default_factory=list)
    aggregation_issues: list[str] = Field(default_factory=list)
    needs_retry: bool = False
    reasoning: str = ""


class SemanticValidationResult(BaseModel):
    valid: bool = True
    retry: bool = False
    score: int = 1
    reasoning: str = ""
    concept_gaps: list[str] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_fix: str = ""

    @property
    def success(self) -> bool:
        return self.valid and not self.retry


class SQLValidatorOutput(BaseModel):
    syntax_valid: bool = True
    syntax_error: str = ""
    missing_tables: list[str] = Field(default_factory=list)
    missing_columns: list[dict[str, str]] = Field(default_factory=list)
    aggregation_issues: list[str] = Field(default_factory=list)
    semantic_valid: bool = True
    concept_gaps: list[str] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_fix: str = ""
    llm_reasoning: str = ""
    needs_retry: bool = False
    logical_ok: bool = True
    score: int = 1
    reasoning: str = ""
    errors: list[str] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.logical_ok and not self.errors


# ---------------------------------------------------------------------------
# LLM validation system prompt
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Layer 1 — AST structural check
# ---------------------------------------------------------------------------


def _build_schema_map(schemas: list[dict]) -> dict[str, set[str]]:
    """Build {schema.table: {cols}, table: {cols}} from retrieved schemas."""
    schema_map: dict[str, set[str]] = {}
    for s in schemas:
        if not isinstance(s, dict):
            continue
        sn = s.get("schema_name", "").lower()
        tn = s.get("table_name", "").lower()
        if not tn:
            continue

        cols: set[str] = set()
        raw_cols = s.get("columns", [])
        if isinstance(raw_cols, list):
            for c in raw_cols:
                if isinstance(c, dict):
                    name = c.get("name", "").lower()
                    if name:
                        cols.add(name)
                elif isinstance(c, str):
                    cols.add(c.lower())

        doc = s.get("document", "")
        if doc and not cols:
            for line in doc.splitlines():
                line = line.strip()
                if line.startswith("- ") and "(" in line:
                    col_name = line[2:].split("(")[0].strip().lower()
                    if col_name:
                        cols.add(col_name)

        key_full = f"{sn}.{tn}" if sn else tn
        schema_map[key_full] = cols
        schema_map[tn] = cols

    return schema_map


def _collect_select_aliases(tree) -> set[str]:
    """
    FIX: Collect all aliases defined in SELECT expressions (e.g. COUNT(...) AS PurchaseCount).
    These are computed aliases — not real schema columns — and must never be
    flagged as missing columns. They are valid in ORDER BY and outer queries.
    """
    aliases: set[str] = set()
    for select in tree.find_all(exp.Select):
        for expr in select.expressions:
            if isinstance(expr, exp.Alias):
                alias_name = expr.alias
                if alias_name:
                    aliases.add(alias_name.lower())
    return aliases


def _collect_cte_names(tree) -> set[str]:
    """
    FIX: Collect CTE names defined via WITH ... AS (...).
    CTEs are temporary named result sets — not real tables — and must never
    be flagged as missing tables.
    """
    cte_names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        alias = getattr(cte, "alias", None)
        if alias is None:
            alias = getattr(cte, "alias_or_name", None)
        if alias:
            name = getattr(alias, "name", None) or str(alias)
            if name:
                cte_names.add(name.lower())
    return cte_names


def _resolve_table_key(node: exp.Table, schemas: list[dict]) -> str:
    db = getattr(node, "db", None) or getattr(node, "catalog", None)
    name = getattr(node, "name", None)
    if not name:
        return ""

    if db:
        return f"{db}.{name}".lower()

    for s in schemas:
        schema_name = s.get("schema_name", "")
        table_name = s.get("table_name", "")
        if table_name and table_name.lower() == name.lower():
            return (
                f"{schema_name}.{table_name}".lower()
                if schema_name
                else table_name.lower()
            )

    return name.lower()


def _query_table_refs(tree, schemas: list[dict]) -> set[str]:
    refs: set[str] = set()
    for node in tree.find_all(exp.Table):
        name = node.name
        if not name:
            continue
        refs.add(_resolve_table_key(node, schemas))
    return {ref for ref in refs if ref}


def _has_aggregates(tree) -> bool:
    AGG = {"SUM", "COUNT", "AVG", "MIN", "MAX", "COUNT_BIG"}
    for n in tree.walk():
        if isinstance(n, exp.Anonymous) and getattr(n, "name", "").upper() in AGG:
            return True
        if isinstance(n, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
            return True
    return False


def validate_sql_structure(
    sql: str,
    schemas: list[dict],
) -> StructuralValidationResult:
    """
    Layer 1 — pure AST checks via sqlglot.

    Checks:
      1. Syntax          — can sqlglot parse this SQL
      2. Table existence — every referenced table is in the schema map
                           (CTEs excluded — they are not real tables)
      3. Column existence — every qualified column is in that table
                            (SELECT aliases excluded — they are not schema columns)
      4. GROUP BY completeness — non-aggregated SELECT cols in GROUP BY
    """
    result = StructuralValidationResult()
    schema_map = _build_schema_map(schemas)

    # 1. Parse
    try:
        tree = sqlglot.parse_one(sql, dialect="tsql")
    except Exception as exc:
        result.syntax_valid = False
        result.syntax_error = str(exc)
        result.needs_retry = True
        result.reasoning = f"SQL failed to parse: {exc}"
        return result

    # Collect aliases and CTEs upfront so we never flag them
    select_aliases = _collect_select_aliases(tree)  # FIX
    cte_names = _collect_cte_names(tree)  # FIX

    # FIX: collect all column names referenced in ORDER BY —
    # ORDER BY can legally reference SELECT aliases which don't exist
    # as real schema columns (e.g. ORDER BY PurchaseCount DESC).
    order_by_col_names: set[str] = set()
    for order in tree.find_all(exp.Order):
        for ordered in order.find_all(exp.Ordered):
            for c in ordered.find_all(exp.Column):
                order_by_col_names.add(c.name.lower())

    # 2. Table existence (skip CTEs)
    found_tables: set[str] = set()
    for node in tree.find_all(exp.Table):
        name = node.name
        if not name:
            continue
        if name.lower() in cte_names:  # FIX: CTEs are not real tables
            continue
        schema = getattr(node, "db", None) or getattr(node, "catalog", None)
        key = f"{schema}.{name}".lower() if schema else name.lower()
        found_tables.add(key)

    missing_tables = [t for t in found_tables if t not in schema_map]
    if missing_tables:
        result.missing_tables = missing_tables
        result.needs_retry = True

    # 3. Column existence (skip SELECT aliases)
    # 3. Column existence (skip SELECT aliases and string literals)
    missing_columns: list[dict[str, str]] = []
    query_tables = _query_table_refs(tree, schemas)
    for col in tree.find_all(exp.Column):
        # FIX: skip string literals misidentified as columns by sqlglot
        name_node = getattr(col, "this", None)
        if getattr(name_node, "is_string", False) or isinstance(name_node, str):
            continue

        tbl = (col.table or "").lower()
        col_name = col.name.lower()

        # Belt-and-suspenders: also catch quote-prefixed names that slipped through
        if col_name.startswith("'") or col_name.startswith('"'):
            continue

        if col_name in select_aliases:  # FIX: computed aliases are valid
            continue
        if col_name in order_by_col_names:  # FIX: ORDER BY may reference aliases
            continue

        if tbl and tbl in schema_map:
            if col_name not in schema_map[tbl]:
                missing_columns.append({"table": tbl, "column": col_name})
        elif not tbl:
            candidate_tables = query_tables or set(schema_map.keys())
            if not any(
                col_name in schema_map.get(table, set()) for table in candidate_tables
            ):
                missing_columns.append({"table": "", "column": col_name})

    if missing_columns:
        result.missing_columns = missing_columns
        result.needs_retry = True

    # 4. GROUP BY completeness
    try:
        if _has_aggregates(tree):
            AGG = {"SUM", "COUNT", "AVG", "MIN", "MAX", "COUNT_BIG"}

            def _contains_agg(node) -> bool:
                for n in node.walk():
                    if (
                        isinstance(n, exp.Anonymous)
                        and getattr(n, "name", "").upper() in AGG
                    ):
                        return True
                    if isinstance(n, (exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
                        return True
                return False

            selects = list(tree.find_all(exp.Select))
            non_agg_cols: list[str] = []
            if selects:
                for expr in selects[0].expressions:
                    if not _contains_agg(expr):
                        for c in expr.find_all(exp.Column):
                            col_name = c.name.lower()
                            if col_name not in select_aliases:  # FIX: skip aliases
                                non_agg_cols.append(col_name)

            group_cols: set[str] = set()
            for g in tree.find_all(exp.Group):
                for ge in g.expressions:
                    if isinstance(ge, exp.Column):
                        group_cols.add(ge.name.lower())
                    else:
                        group_cols.update(
                            c.name.lower() for c in ge.find_all(exp.Column)
                        )

            missing_from_group = [c for c in non_agg_cols if c not in group_cols]
            if missing_from_group:
                result.aggregation_issues = missing_from_group
                result.needs_retry = True
    except Exception:
        pass

    reasons: list[str] = []
    if result.missing_tables:
        reasons.append(f"Tables not in schema: {result.missing_tables}")
    if result.missing_columns:
        reasons.append(f"Columns not in schema: {result.missing_columns}")
    if result.aggregation_issues:
        reasons.append(f"Missing from GROUP BY: {result.aggregation_issues}")

    result.reasoning = "; ".join(reasons) if reasons else "Structural checks passed."
    return result


# ---------------------------------------------------------------------------
# Layer 2 — LLM semantic validation
# ---------------------------------------------------------------------------


def _extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("No JSON object found", raw, 0)
    return raw[start : end + 1]


def validate_sql_with_llm(
    llm: BaseLLM,
    user_query: str,
    generated_sql: str,
    schemas_context: str,
    seed_tables: list[str],
    join_paths_context: str,
    structural: StructuralValidationResult,
    system_prompt: str | None = None,
) -> SemanticValidationResult:
    """Layer 2 — LLM reasons about intent, semantics, and logic."""
    if not system_prompt:
        system_prompt = SQL_VALIDATION_SYSTEM
    structural_summary = {
        k: v
        for k, v in structural.model_dump(
            include={
                "missing_tables",
                "missing_columns",
                "aggregation_issues",
                "reasoning",
            }
        ).items()
        if v not in ([], "", {})
    }

    payload = json.dumps(
        {
            "UserQuery": user_query,
            "GeneratedSQL": generated_sql,
            "SeedTables": ", ".join(seed_tables),
            "Schemas": schemas_context,
            "JoinPaths": join_paths_context,
            "StructuralIssues": structural_summary or "None found.",
        },
        ensure_ascii=False,
    )

    try:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "sql_validation",
                "schema": SemanticValidationResult.model_json_schema(),
            },
        }

        raw = llm.generate(
            system_prompt=system_prompt,
            user_prompt=payload,
            response_format=response_format,
            json_mode=True,
        )

        if not raw:
            raise ValueError("Empty LLM response")

        if isinstance(raw, (dict, list)):
            parsed = raw if isinstance(raw, dict) else raw[0]
        else:
            parsed = json.loads(_extract_json(raw))
    except Exception as exc:
        logger.warning(f"LLM validator error: {exc}")
        return SemanticValidationResult(
            valid=False,
            retry=False,
            score=0,
            reasoning=f"validator_error: {exc}",
        )

    # FIX: enforce retry=false when there are no critical issues
    # The LLM sometimes sets retry=true on warnings only — guard against that here.
    critical_issues = list(parsed.get("critical_issues", []))
    retry_requested = bool(parsed.get("retry", False))
    retry_safe = retry_requested and len(critical_issues) > 0  # FIX

    return SemanticValidationResult(
        valid=bool(parsed.get("valid", False)),
        retry=retry_safe,  # FIX: never retry on warnings only
        score=int(parsed.get("score", 1 if parsed.get("valid") else 0)),
        reasoning=str(parsed.get("reasoning", "")),
        concept_gaps=list(parsed.get("concept_gaps", [])),
        critical_issues=critical_issues,
        warnings=list(parsed.get("warnings", [])),
        suggested_fix=str(parsed.get("suggested_fix", "")),
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _append_validation_log(entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with SQL_VALIDATION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def sql_validator_node(
    llm: BaseLLM,
    state: dict[str, Any],
) -> dict[str, Any]:
    """
    LangGraph node: validate generated SQL against schemas and user intent.

    Consumes:
        state["generated_sql"]     — SQL to validate
        state["construct"]         — dict with constructed_query
        state["retrieved_schemas"] — list of schema dicts
        state["seed_tables"]       — list[str]
        state["join_paths"]        — list[dict | str]

    Produces:
        state["validation_result"] — SQLValidatorOutput as dict
        state["validation_passed"] — bool
        state["validation_errors"] — list[str]
        state["suggested_fix"]     — str (populated when retry needed)
    """
    logger.info("Starting SQL Validator")

    def _fail(reason: str) -> dict[str, Any]:
        logger.error(f"SQL Validator failed: {reason}")
        output = SQLValidatorOutput(
            needs_retry=True,
            logical_ok=False,
            score=0,
            reasoning=reason,
            errors=[reason],
        )
        return {
            **state,
            "validation_result": output.model_dump(),
            "validation_passed": False,
            "validation_errors": [reason],
            "suggested_fix": "",
        }

    sql: str = state.get("generated_sql", "").strip()
    if not sql:
        return _fail("No generated_sql in state — run sql_generator_node first")

    construct = state.get("construct", {})
    if isinstance(construct, str):
        user_query = construct
    elif isinstance(construct, dict):
        user_query = construct.get("constructed_query", state.get("user_query", ""))
    else:
        user_query = state.get("user_query", "")

    if not user_query:
        return _fail("No user query found in state")

    schemas: list[dict] = state.get("retrieved_schemas", [])
    if not isinstance(schemas, list):
        schemas = []

    seed_tables: list[str] = state.get("seed_tables", [])
    if not isinstance(seed_tables, list):
        seed_tables = []

    join_paths: list[dict | str] = state.get("join_paths", [])
    if not isinstance(join_paths, list):
        join_paths = []

    # Format contexts for LLM using shared helpers
    try:
        schemas_context = _format_schemas_for_llm(schemas)
        join_paths_context = _format_join_paths_for_llm(join_paths)
    except Exception:
        schemas_context = json.dumps(schemas, ensure_ascii=False, default=str)
        join_paths_context = json.dumps(join_paths, ensure_ascii=False, default=str)

    # Layer 1
    logger.info("Layer 1: structural AST check")
    structural = validate_sql_structure(sql=sql, schemas=schemas)
    logger.info(f"Structural: {structural.reasoning}")

    # Layer 2
    logger.info("Layer 2: LLM semantic check")
    semantic = validate_sql_with_llm(
        llm=llm,
        user_query=user_query,
        generated_sql=sql,
        schemas_context=schemas_context,
        seed_tables=seed_tables,
        join_paths_context=join_paths_context,
        structural=structural,
    )
    logger.info(f"Semantic: valid={semantic.valid}, retry={semantic.retry}")

    # Merge — retry only when there are actual critical issues
    needs_retry = structural.needs_retry or semantic.retry
    logical_ok = not needs_retry

    all_issues: list[str] = []
    if structural.needs_retry:
        all_issues.append(f"[structural] {structural.reasoning}")
    all_issues.extend(f"[critical] {i}" for i in semantic.critical_issues)
    all_issues.extend(f"[gap] {g}" for g in semantic.concept_gaps)

    output = SQLValidatorOutput(
        syntax_valid=structural.syntax_valid,
        syntax_error=structural.syntax_error,
        missing_tables=structural.missing_tables,
        missing_columns=structural.missing_columns,
        aggregation_issues=structural.aggregation_issues,
        semantic_valid=semantic.valid,
        concept_gaps=semantic.concept_gaps,
        critical_issues=semantic.critical_issues,
        warnings=semantic.warnings,
        suggested_fix=semantic.suggested_fix,
        llm_reasoning=semantic.reasoning,
        needs_retry=needs_retry,
        logical_ok=logical_ok,
        score=0 if (needs_retry or not semantic.valid) else 1,
        reasoning=(
            f"[structural] {structural.reasoning} | " f"[semantic] {semantic.reasoning}"
        ),
        errors=all_issues,
    )

    logger.info(
        f"Validation complete — needs_retry={needs_retry}, "
        f"score={output.score}, issues={len(all_issues)}"
    )

    final_state = {
        **state,
        "validation_result": output.model_dump(),
        "validation_passed": logical_ok,
        "validation_errors": all_issues,
        "suggested_fix": semantic.suggested_fix,
        "retry_feedback": (
            {
                "issues": semantic.critical_issues + semantic.concept_gaps,
                "reasoning": semantic.reasoning,
                "failed_sql": sql,
                "hint": semantic.suggested_fix,
                "attempt": state.get("retry_count", 0) + 1,
            }
            if needs_retry
            else state.get("retry_feedback")
        ),
    }

    _append_validation_log(
        {
            "user_query": user_query,
            "generated_sql": sql,
            "structural": structural.model_dump(),
            "semantic": semantic.model_dump(),
            "output": output.model_dump(),
        }
    )

    # Pretty print concise terminal summary for debugging
    pretty_log(
        "SQLValidator",
        state={"user_query": user_query, "generated_sql": sql},
        llm_metrics=None,
        extra={"needs_retry": needs_retry, "issues": all_issues, "score": output.score},
    )

    return final_state
