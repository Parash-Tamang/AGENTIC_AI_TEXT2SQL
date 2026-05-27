"""
SQL Generator — generates SQL from user's constructed query via LLM.

Fixes applied:
  1. sqlglot-based table ref extraction (no alias.column false positives)
  2. Column-level hallucination detection (new)
  3. Retry loop with forbidden-table AND forbidden-column injection on hallucination
  4. Optional SQLCoder refiner — pass sqlcoder_llm=None to disable completely
  5. SELECT aliases and CTE names excluded from column hallucination detection
  6. RBAC enforcer removed — runs as dedicated graph node after validation
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import sqlglot
import sqlglot.expressions as exp
import tiktoken
from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM
from src.agent.utils.pretty_print import pretty_log
from src.agent.nodes.sql_refiner import refine_sql
from src.agent.prompt.sql_generator import SQL_GENERATION_SYSTEM
from src.agent.utils.prompt_utils import resolve_system_prompt

# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
SQL_GENERATION_LOG = LOG_DIR / "sql_generation.jsonl"

MAX_RETRIES = 2


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────


class TokenBreakdown(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class SQLGeneratorOutput(BaseModel):
    sql: str = ""
    tables_used: list[str] = Field(default_factory=list)
    reasoning: str = ""
    hallucination_check: str | dict[str, Any] = ""
    token_breakdown: TokenBreakdown = Field(default_factory=TokenBreakdown)
    errors: list[str] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.sql) and not self.errors


class SQLGeneratorError(BaseModel):
    sql: str = ""
    tables_used: list[str] = Field(default_factory=list)
    reasoning: str = ""
    hallucination_check: str | dict[str, Any] = ""
    token_breakdown: TokenBreakdown = Field(default_factory=TokenBreakdown)
    errors: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Token counting
# ─────────────────────────────────────────────────────────────────────────────

_TIKTOKEN_ENCODING = tiktoken.get_encoding("o200k_base")


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        return len(_TIKTOKEN_ENCODING.encode(text))
    except Exception:
        return len(text.split()) * 2


# ─────────────────────────────────────────────────────────────────────────────
# JSON extraction
# ─────────────────────────────────────────────────────────────────────────────


def _extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise json.JSONDecodeError("No JSON object found in LLM output", raw, 0)
    return raw[start : end + 1]


def _parse_llm_json(raw: str) -> dict:
    cleaned = _extract_json(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        cleaned = cleaned.replace("\r", "\\r").replace("\t", "\\t")
        return json.loads(cleaned, strict=False)


# ─────────────────────────────────────────────────────────────────────────────
# Schema / join path formatters
# ─────────────────────────────────────────────────────────────────────────────


def _format_schemas_for_llm(schemas: list[dict]) -> str:
    parts: list[str] = []
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        document = schema.get("document", "").strip()
        if document:
            parts.append(document)
            continue
        schema_name = schema.get("schema_name", "UNKNOWN_SCHEMA")
        table_name = schema.get("table_name", "UNKNOWN_TABLE")
        description = schema.get("description", "")
        lines = [f"Table: {schema_name}.{table_name}"]
        if description:
            lines.append(f"Description: {description}")
        columns = schema.get("columns", [])
        if columns:
            lines.append("Columns:")
            for col in columns:
                if isinstance(col, str):
                    lines.append(f"  - {col}")
                    continue
                if not isinstance(col, dict):
                    continue
                name = col.get("name", "?")
                col_type = col.get("type", "UNKNOWN")
                desc = col.get("description", "")
                constraints = []
                if col.get("is_primary_key"):
                    constraints.append("PK")
                if col.get("is_foreign_key"):
                    constraints.append("FK")
                if not col.get("nullable", True):
                    constraints.append("NOT NULL")
                sig = f"  - {name} ({col_type})"
                if constraints:
                    sig += f" [{', '.join(constraints)}]"
                lines.append(sig)
                if desc:
                    lines.append(f"      └─ {desc}")
        else:
            lines.append("  (no column metadata available)")
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


def _format_join_paths_for_llm(join_paths: list[dict | str]) -> str:
    if not join_paths:
        return "None"
    parts: list[str] = []
    for i, jp in enumerate(join_paths, 1):
        if isinstance(jp, str):
            parts.append(f"  {jp}")
            continue
        if not isinstance(jp, dict):
            continue
        path = " → ".join(jp.get("path", []))
        hops = jp.get("hops", 0)
        parts.append(f"Path {i}: {path} ({hops} hops)")
        for rel in jp.get("relationships", []):
            if not isinstance(rel, dict):
                continue
            parts.append(
                f"  JOIN ON {rel.get('from_table','?')}.{rel.get('from_column','?')}"
                f" = {rel.get('to_table','?')}.{rel.get('to_column','?')}"
                f"  [{rel.get('relationship_type','INNER JOIN')}]"
            )
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Table ref extraction
# ─────────────────────────────────────────────────────────────────────────────


def _extract_table_refs_from_sql(sql: str) -> set[str]:
    try:
        tree = sqlglot.parse_one(sql, dialect="tsql")
        refs: set[str] = set()
        for node in tree.find_all(exp.Table):
            db = node.args.get("db")
            name = node.name
            if not name:
                continue
            refs.add(f"{db}.{name}".lower() if db else name.lower())
        return refs
    except Exception:
        logger.debug("sqlglot parse failed, falling back to regex")
        pattern = r"(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)"
        return {m.lower() for m in re.findall(pattern, sql, re.IGNORECASE)}


def _known_table_refs(schemas: list[dict]) -> set[str]:
    known: set[str] = set()
    for s in schemas:
        sn = s.get("schema_name", "")
        tn = s.get("table_name", "")
        if sn and tn:
            known.add(f"{sn}.{tn}".lower())
        if tn:
            known.add(tn.lower())
    return known


def _detect_hallucinated_tables(sql: str, schemas: list[dict]) -> list[str]:
    known = _known_table_refs(schemas)
    found = _extract_table_refs_from_sql(sql)
    return sorted(found - known)


# ─────────────────────────────────────────────────────────────────────────────
# Column hallucination detection
# ─────────────────────────────────────────────────────────────────────────────


def _known_column_refs(schemas: list[dict]) -> dict[str, set[str]]:
    known: dict[str, set[str]] = {}
    for s in schemas:
        sn = s.get("schema_name", "")
        tn = s.get("table_name", "")
        if not (sn and tn):
            continue
        key = f"{sn}.{tn}".lower()
        cols: set[str] = set()
        for col in s.get("columns", []):
            if isinstance(col, dict):
                name = col.get("name", "").strip()
                if name:
                    cols.add(name.lower())
            elif isinstance(col, str):
                cols.add(col.strip().lower())
        if not cols:
            document = s.get("document", "")
            for line in document.splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    col_name = stripped[2:].split()[0].lower()
                    if col_name:
                        cols.add(col_name)
        known[key] = cols
    return known


def _resolve_table_key(node: exp.Table, schemas: list[dict]) -> str:
    db = node.args.get("db")
    name = node.name
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


def _extract_query_table_refs(sql: str, schemas: list[dict]) -> set[str]:
    try:
        tree = sqlglot.parse_one(sql, dialect="tsql")
        refs: set[str] = set()
        for node in tree.find_all(exp.Table):
            refs.add(_resolve_table_key(node, schemas))
        return {ref for ref in refs if ref}
    except Exception:
        return _known_table_refs(schemas)


def _extract_column_refs_from_sql(
    sql: str, schemas: list[dict]
) -> list[tuple[str, str]]:
    """
    Extract (table_key, column_name) pairs from SQL for hallucination detection.

    Correctly excludes:
      - SELECT aliases (COUNT(*) AS total — 'total' is not a schema column)
      - CTE names (WITH cte AS (...) — 'cte' is not a real table)
      - ORDER BY references to SELECT aliases (ORDER BY total DESC)
      - String literals misidentified as columns by sqlglot
    """
    alias_map: dict[str, str] = {}

    try:
        tree = sqlglot.parse_one(sql, dialect="tsql")

        # Collect SELECT aliases — computed expressions, not real schema columns
        select_aliases: set[str] = set()
        for select in tree.find_all(exp.Select):
            for expr in select.expressions:
                if isinstance(expr, exp.Alias):
                    alias_name = expr.alias
                    if alias_name:
                        select_aliases.add(alias_name.lower())

        # Collect CTE names — virtual tables, not real schema tables
        cte_names: set[str] = set()
        for cte in tree.find_all(exp.CTE):
            name = cte.alias
            if name:
                cte_names.add(name.lower())

        # Collect ORDER BY column names that are SELECT aliases
        # ORDER BY total DESC is valid when total is a SELECT alias
        order_by_alias_refs: set[str] = set()
        for order in tree.find_all(exp.Order):
            for ordered in order.find_all(exp.Ordered):
                for c in ordered.find_all(exp.Column):
                    col = c.name.lower()
                    if col in select_aliases:
                        order_by_alias_refs.add(col)

        # Build table alias map (skip CTEs — they are not real schema tables)
        for node in tree.find_all(exp.Table):
            name = node.name
            alias = node.alias
            if not name:
                continue
            if name.lower() in cte_names:
                continue
            full_key = _resolve_table_key(node, schemas)
            if alias:
                alias_map[alias.lower()] = full_key
            alias_map[name.lower()] = full_key

        query_tables = {
            table_key
            for table_key in alias_map.values()
            if table_key and table_key != "__unqualified__"
        }

        pairs: list[tuple[str, str]] = []
        for node in tree.find_all(exp.Column):
            col_name = node.name
            table_ref = node.table

            if not col_name or col_name == "*":
                continue

            # Skip string literals misidentified as columns
            name_node = node.args.get("this")
            if isinstance(name_node, exp.Literal):
                continue

            col_lower = col_name.lower()

            if col_lower.startswith("'") or col_lower.startswith('"'):
                continue

            # Skip SELECT aliases — not real schema columns
            if col_lower in select_aliases:
                continue

            # Skip ORDER BY references to SELECT aliases
            if col_lower in order_by_alias_refs:
                continue

            if table_ref:
                resolved = alias_map.get(table_ref.lower())
                if resolved:
                    pairs.append((resolved, col_lower))
                else:
                    pairs.append(("__unqualified__", col_lower))
            else:
                if query_tables:
                    for table_key in query_tables:
                        pairs.append((table_key, col_lower))
                else:
                    pairs.append(("__unqualified__", col_lower))

        print(pairs)
        return pairs
    except Exception as exc:
        logger.debug(f"sqlglot column extraction failed: {exc}")
        return []


def _detect_hallucinated_columns(sql: str, schemas: list[dict]) -> list[str]:
    known_cols = _known_column_refs(schemas)
    query_tables = _extract_query_table_refs(sql, schemas)
    col_refs = _extract_column_refs_from_sql(sql, schemas)
    hallucinated: list[str] = []

    logger.debug(f"known_cols keys: {list(known_cols.keys())}")
    logger.debug(f"query_tables: {sorted(query_tables)}")
    logger.debug(f"col_refs: {col_refs}")

    for table_key, col_name in col_refs:
        if table_key == "__unqualified__":
            candidate_tables = query_tables or set(known_cols.keys())
            if not any(
                col_name in known_cols.get(table, set()) for table in candidate_tables
            ):
                hallucinated.append(f"(unqualified).{col_name}")
        else:
            table_cols = known_cols.get(table_key)
            if table_cols is not None and col_name not in table_cols:
                hallucinated.append(f"{table_key}.{col_name}")

    return sorted(set(hallucinated))


# ─────────────────────────────────────────────────────────────────────────────
# Retry prompt injection
# ─────────────────────────────────────────────────────────────────────────────


def _inject_correction(
    user_prompt_json: str,
    hallucinated_tables: list[str],
    hallucinated_columns: list[str],
) -> str:
    parsed = json.loads(user_prompt_json)
    issues: list[str] = []

    if hallucinated_tables:
        issues.append(
            "HALLUCINATED TABLES (do not exist in AuthoritativeTables):\n"
            + "\n".join(f"  ✗ {t}" for t in hallucinated_tables)
            + "\n\nRewrite the SQL using ONLY tables from AuthoritativeTables. "
            "If a concept cannot be satisfied by any available table, omit it entirely."
        )

    if hallucinated_columns:
        issues.append(
            "HALLUCINATED COLUMNS (do not exist in Schemas):\n"
            + "\n".join(f"  ✗ {c}" for c in hallucinated_columns)
            + "\n\nFor each ✗ column above, look up the real column name in the "
            "Schemas block and use that instead. Do NOT invent column names."
        )

    if issues:
        parsed["CorrectionFromPreviousAttempt"] = (
            "YOUR PREVIOUS SQL FAILED VALIDATION.\n\n" + "\n\n".join(issues)
        )

    return json.dumps(parsed, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────


def _append_sql_generation_log(entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with SQL_GENERATION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# SQL Generator Node
# ─────────────────────────────────────────────────────────────────────────────


def sql_generator_node(
    llm: BaseLLM,
    state: dict[str, Any],
    sqlcoder_llm: Optional[BaseLLM] = None,
) -> dict[str, Any]:
    """
    LangGraph node: generate SQL from constructed query + schemas + join paths.

    Consumes:
        state["construct"]["constructed_query"]
        state["retrieved_schemas"]      — list of SchemaResult dicts
        state["seed_tables"]            — list[str]
        state["join_paths"]             — list[dict | str]
        state["mandatory_filters"]      — dict (column names only, no values)
        state["retry_feedback"]         — dict (populated on validation failure)

    Produces:
        state["generated_sql"]          — raw LLM output, no RBAC rewrite
        state["token_count"]            — int
        state["token_breakdown"]        — dict
        state["sql_errors"]             — list[str]
        state["hallucinated_tables"]    — list[str]
        state["hallucinated_columns"]   — list[str]

    Note: RBAC enforcement is handled by rbac_enforcer_node which runs
    after sql_validator_node. This node never touches RBAC values.
    """
    logger.info("Starting SQL Generator")
    logger.info(f"SQLCoder refiner: {'ENABLED' if sqlcoder_llm else 'DISABLED'}")

    def _fail(reason: str, exc: str = "") -> dict[str, Any]:
        errors = [reason] + ([exc] if exc else [])
        logger.error(f"SQL Generator failed: {reason}")
        return {
            **state,
            "generated_sql": "",
            "token_count": 0,
            "token_breakdown": TokenBreakdown().model_dump(),
            "sql_errors": errors,
            "hallucinated_tables": [],
            "hallucinated_columns": [],
        }

    # ── extract inputs ────────────────────────────────────────────────────────

    construct = state.get("construct", {})
    if isinstance(construct, str):
        user_query = construct
    elif isinstance(construct, dict):
        user_query = construct.get("constructed_query", state.get("user_query", ""))
    else:
        user_query = state.get("user_query", "")

    schemas: list[dict] = state.get("retrieved_schemas", [])
    if not isinstance(schemas, list):
        schemas = []

    seed_tables: list[str] = state.get("seed_tables", [])
    if not isinstance(seed_tables, list):
        seed_tables = []

    join_paths: list[dict | str] = state.get("join_paths", [])
    if not isinstance(join_paths, list):
        join_paths = []

    # mandatory_filters: column structure only — values are stripped so the
    # LLM uses the user's intent. The RBAC enforcer locks values after validation.
    mandatory_filters: dict[str, dict] = state.get("mandatory_filters", {})

    if not user_query:
        return _fail("No constructed query in state")
    if not schemas:
        return _fail("No schemas in retrieved_schemas")
    if not seed_tables:
        return _fail("No seed tables in state")

    # ── build prompt ──────────────────────────────────────────────────────────

    schemas_context = _format_schemas_for_llm(schemas)
    join_paths_context = _format_join_paths_for_llm(join_paths)
    seed_tables_ctx = ", ".join(str(t) for t in seed_tables if t)

    known_tables = sorted(_known_table_refs(schemas))
    authoritative_block = (
        "AUTHORITATIVE TABLE LIST — ONLY these tables exist in this database.\n"
        "Do not reference any table not listed here.\n"
        + "\n".join(f"  • {t}" for t in known_tables)
    )

    base_payload: dict[str, Any] = {
        "UserQuery": user_query,
        "SeedTables": seed_tables_ctx,
        "AuthoritativeTables": authoritative_block,
        "Schemas": schemas_context,
        "JoinPaths": join_paths_context,
    }

    # Inject mandatory filter column names only — no values.
    # The LLM must include these columns in WHERE using the user's intent value.
    # The RBAC enforcer will lock the actual permitted value after validation.
    if mandatory_filters:
        logger.info(f"Injecting {len(mandatory_filters)} mandatory filter requirements")
        base_payload["MandatoryFilters"] = {
            table: {
                col: {"filter": meta.get("filter")} for col, meta in filters.items()
            }
            for table, filters in mandatory_filters.items()
        }

    retry_feedback = state.get("retry_feedback")
    if retry_feedback and isinstance(retry_feedback, dict):
        failed_sql = retry_feedback.get("failed_sql", "")
        hint = retry_feedback.get("hint", "")
        issues = retry_feedback.get("issues", [])
        reasoning = retry_feedback.get("reasoning", "")
        attempt = retry_feedback.get("attempt", 1)

        if failed_sql:
            base_payload["RetryFeedback"] = {
                "Attempt": attempt,
                "PreviousSQLThatFailed": failed_sql,
                "ValidationIssues": issues,
                "Reasoning": reasoning,
                "SuggestedFix": hint,
                "Instruction": (
                    "Your previous SQL was rejected. "
                    "You MUST address every issue listed above. "
                    "Use SuggestedFix as a starting point but ensure "
                    "full schema compliance."
                ),
            }
            logger.info(
                f"Retry feedback injected — attempt={attempt}, hint={hint[:80]}"
            )

    user_prompt = json.dumps(base_payload, ensure_ascii=False)
    system_prompt = resolve_system_prompt(state, "sql_generator", SQL_GENERATION_SYSTEM)
    prompt_tokens = _count_tokens(system_prompt + user_prompt)
    logger.info(f"Prompt tokens (attempt 1): {prompt_tokens}")

    # ── retry loop ────────────────────────────────────────────────────────────

    result: dict = {}
    sql: str = ""
    hallucinated_tables: list[str] = []
    hallucinated_cols: list[str] = []
    raw: str = ""

    for attempt in range(MAX_RETRIES + 1):
        logger.info(f"LLM attempt {attempt + 1}/{MAX_RETRIES + 1}")

        try:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "sql_generation",
                    "schema": SQLGeneratorOutput.model_json_schema(),
                },
            }
            raw = llm.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=response_format,
                json_mode=True,
            )
            logger.debug(f"Raw LLM output (first 500):\n{raw[:500]}")
        except Exception as exc:
            logger.error(f"LLM call failed on attempt {attempt + 1}: {exc}")
            if attempt == MAX_RETRIES:
                return _fail("LLM call failed after all retries", str(exc))
            continue

        if not raw or not raw.strip():
            if attempt == MAX_RETRIES:
                return _fail(
                    "LLM returned empty response — prompt may exceed context window",
                    f"prompt_tokens={prompt_tokens}",
                )
            continue

        try:
            if isinstance(raw, (dict, list)):
                result = raw
            else:
                result = _parse_llm_json(raw)
        except json.JSONDecodeError as exc:
            logger.error(f"JSON parse failed on attempt {attempt + 1}: {exc}")
            if attempt == MAX_RETRIES:
                return _fail(
                    "LLM response was not valid JSON after all retries", str(exc)
                )
            continue

        sql = result.get("sql", "").strip()
        if not sql:
            if attempt == MAX_RETRIES:
                return _fail("LLM returned empty sql field after all retries")
            continue

        # ── hallucination detection ───────────────────────────────────────────
        hallucinated_tables = _detect_hallucinated_tables(sql, schemas)
        hallucinated_cols = _detect_hallucinated_columns(sql, schemas)
        try:
            hallucinated_cols = sorted({c.lower() for c in (hallucinated_cols or [])})
        except Exception:
            pass

        logger.debug(f"Detected hallucinated_tables={hallucinated_tables}")
        logger.debug(f"Detected hallucinated_columns={hallucinated_cols}")

        if not hallucinated_tables and not hallucinated_cols:
            logger.info(f"No hallucinations detected on attempt {attempt + 1}.")
            break

        if hallucinated_tables:
            logger.warning(
                f"Attempt {attempt + 1}: hallucinated tables: {hallucinated_tables}"
            )
        if hallucinated_cols:
            logger.warning(
                f"Attempt {attempt + 1}: hallucinated columns: {hallucinated_cols}"
            )

        # ── SQLCoder refiner (first-line fix before Llama retry) ─────────────
        refined_sql, was_refined = refine_sql(
            sql=sql,
            schemas=schemas,
            sqlcoder_llm=sqlcoder_llm,
            hallucinated_tables=hallucinated_tables,
            hallucinated_cols=hallucinated_cols,
        )

        if was_refined:
            r_tables = _detect_hallucinated_tables(refined_sql, schemas)
            r_cols = _detect_hallucinated_columns(refined_sql, schemas)
            r_cols = sorted({c.lower() for c in (r_cols or [])})

            if not r_tables and not r_cols:
                logger.info("SQLCoder fixed all hallucinations — skipping Llama retry")
                sql = refined_sql
                hallucinated_tables = []
                hallucinated_cols = []
                break
            else:
                logger.warning(
                    f"SQLCoder could not fully fix — remaining tables={r_tables}, cols={r_cols}"
                )
                hallucinated_tables = r_tables
                hallucinated_cols = r_cols

        if attempt < MAX_RETRIES:
            user_prompt = _inject_correction(
                user_prompt, hallucinated_tables, hallucinated_cols
            )
            logger.info("Correction block injected (tables + columns). Retrying...")
        else:
            error_parts: list[str] = []
            if hallucinated_tables:
                error_parts.append(f"tables: {hallucinated_tables}")
            if hallucinated_cols:
                error_parts.append(f"columns: {hallucinated_cols}")
            return _fail(
                f"Hallucinations persist after {MAX_RETRIES + 1} attempts — "
                + ", ".join(error_parts)
            )

    # ── assemble output ───────────────────────────────────────────────────────

    completion_tokens = _count_tokens(raw)
    total_tokens = prompt_tokens + completion_tokens

    output = SQLGeneratorOutput(
        sql=sql,
        tables_used=result.get("tables_used", []),
        reasoning=result.get("reasoning", ""),
        hallucination_check=result.get("hallucination_check", ""),
        token_breakdown=TokenBreakdown(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )

    logger.info(f"Generated SQL (first 120): {sql[:120]}...")
    logger.info(
        f"Tokens — prompt: {prompt_tokens}, "
        f"completion: {completion_tokens}, total: {total_tokens}"
    )

    final_state = {
        **state,
        "generated_sql": output.sql,
        "token_count": total_tokens,
        "token_breakdown": output.token_breakdown.model_dump(),
        "sql_errors": [],
        "hallucinated_tables": hallucinated_tables,
        "hallucinated_columns": hallucinated_cols,
        # rbac_enforced_filters is NOT set here — rbac_enforcer_node sets it
        # after validation passes. Generator never touches RBAC values.
    }

    _append_sql_generation_log(
        {
            "input_state": state,
            "llm_raw_output": raw,
            "parsed_result": result,
            "output_model": output.model_dump(),
            "final_state": final_state,
        }
    )

    try:
        pretty_log(
            "SQLGenerator",
            state={"user_query": user_query, "generated_sql": output.sql[:400]},
            llm_metrics={
                "token_breakdown": output.token_breakdown.model_dump(),
                "latency_ms": None,
            },
            extra={
                "hallucinated_tables": hallucinated_tables,
                "hallucinated_columns": hallucinated_cols,
                "sqlcoder_refiner": "enabled" if sqlcoder_llm else "disabled",
            },
        )
    except Exception:
        print(f"\n{'='*70}\nFINAL OUTPUT\n{'='*70}")
        print(f"Generated SQL:\n{output.sql}")
        print(f"\n{'='*70}\n")

    return final_state
