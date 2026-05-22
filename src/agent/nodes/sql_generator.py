"""
SQL Generator — generates SQL from user's constructed query via LLM.

Fixes applied:
  1. sqlglot-based table ref extraction (no alias.column false positives)
  3. Retry loop with forbidden-table injection on hallucination
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlglot
import sqlglot.expressions as exp
import tiktoken
from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM

# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
SQL_GENERATION_LOG = LOG_DIR / "sql_generation.jsonl"

MAX_RETRIES = 2

# ─────────────────────────────────────────────────────────────────────────────
# System prompt (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

SQL_GENERATION_SYSTEM = """\
You are a T-SQL Generator. Convert natural language into a single valid T-SQL SELECT statement.

══════════════════════════════════════════════════════════════════
CONTEXT YOU WILL RECEIVE
══════════════════════════════════════════════════════════════════
- UserQuery           : Natural language question to answer with SQL
- AuthoritativeTables : COMPLETE list of tables that exist — use no others
- Schemas             : Full column metadata for each table in AuthoritativeTables
- SeedTables          : Primary tables most relevant to the query
- JoinPaths           : FK relationships and BFS-discovered join paths

══════════════════════════════════════════════════════════════════
RETRY FEEDBACK (only present on retry attempts)
══════════════════════════════════════════════════════════════════
If RetryFeedback is present:
- PreviousSQLThatFailed : the exact SQL that was rejected — DO NOT repeat it
- ValidationIssues      : specific problems found
- SuggestedFix          : concrete rewrite hint from the validator — USE IT
- You MUST fix every issue. Generating the same SQL again is a critical failure.

══════════════════════════════════════════════════════════════════
STRICT SCHEMA ADHERENCE  ← violations cause runtime errors
══════════════════════════════════════════════════════════════════
RULE 1 — ONLY USE TABLES FROM AuthoritativeTables.
  If a table is not listed there, it does NOT exist in this database.
  Do not invent tables. Do not guess table names.

RULE 2 — ONLY USE COLUMNS FROM Schemas.
  Every column reference must appear in that table's column list in Schemas.
  Do not invent columns.

RULE 3 — DERIVE schema_name FROM Schemas, NEVER ASSUME IT.
  Read the exact schema_name from the Schemas context for each table.
  Never default to "dbo", "public", or any schema not present in Schemas.

RULE 4 — FULLY QUALIFIED NAMES EVERYWHERE, NO ALIASES IN JOIN ON.
  Format:
    Table  → schema_name.table_name
    Column → schema_name.table_name.column_name

  ✅ CORRECT:
     FROM  schema_name.Orders
     JOIN  schema_name.Customers
       ON  schema_name.Orders.CustomerID = schema_name.Customers.CustomerID

  ❌ WRONG — aliases in JOIN ON:
     JOIN Customers c ON o.CustomerID = c.CustomerID

  ❌ WRONG — assumed schema:
     FROM dbo.Orders
     FROM public.Orders

RULE 5 — VERIFY EVERY JOIN BEFORE WRITING IT.
  Ask yourself:
    (a) Is this table in AuthoritativeTables?       → if no, drop the join
    (b) Are both join columns in Schemas?           → if no, find the real FK column
  If both checks do not pass, omit that join entirely.

══════════════════════════════════════════════════════════════════
SQL CONSTRUCTION RULES
══════════════════════════════════════════════════════════════════
1. SELECT only — no INSERT, UPDATE, DELETE, DDL, or stored procedures
2. TOP N, WHERE, ORDER BY, GROUP BY, aggregates only when the query implies them
3. COUNT(DISTINCT ...) for distinct entity counts
4. NULLIF(denominator, 0) to guard all divisions against divide-by-zero
5. Keyword search: split multi-word terms into AND-chained LIKE clauses
   "Road W" → col LIKE '%Road%' AND col LIKE '%W%'
6. Relative dates: DATEADD / GETDATE()
7. Window functions (ROW_NUMBER, RANK) only when ranking per partition is needed

POST SQL VALIDATION RULES

1. Validate every referenced table exists.
2. Validate every referenced column exists.
3. Validate every JOIN path exists in schema FK relationships.
4. Validate semantic labels:
   - Do not label ProductModel as SubCategory unless schema explicitly says so.
   - Do not generate SalesTerritory if no such schema exists.
5. Validate aggregations:
   - Non-aggregated columns must appear in GROUP BY.
6. Validate COUNT semantics:
   - DistinctCustomers must count CustomerID, not SalesOrderID.
7. Reject alias.column formats if strict mode enabled.
8. Reject hallucinated business concepts not present in schema descriptions.
9. Reject logically meaningless window functions.
10. Reject over-grouping on transactional fields.

══════════════════════════════════════════════════════════════════
MANDATORY SELF-CHECK BEFORE WRITING OUTPUT
══════════════════════════════════════════════════════════════════
Go through this list before writing your JSON response.
Fix any failures before outputting.

  [ ] Every table in my SQL is in AuthoritativeTables
  [ ] Every column in my SQL is in that table's Schemas entry
  [ ] Every schema_name was read from Schemas, not assumed
  [ ] All JOIN ON conditions use fully qualified names, no aliases
  [ ] All divisions are guarded with NULLIF
  [ ] SQL is SELECT only

══════════════════════════════════════════════════════════════════
OUTPUT — YOUR ENTIRE RESPONSE MUST BE A SINGLE JSON OBJECT
══════════════════════════════════════════════════════════════════
• No text before the JSON
• No text after the JSON
• No markdown fences (no ```)
• No explanations outside the JSON fields
• First character of your response: {
• Last character of your response: }

{
    "sql": "SELECT ...",
    "tables_used": ["schema_name.table_name", ...],
    "hallucination_check": "for each table you used, state: table name → found in AuthoritativeTables yes/no",
    "reasoning": "which tables were chosen, which joins were used, and why"
}
"""

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
# FIX 1 — sqlglot-based table ref extraction (no alias.column false positives)
# ─────────────────────────────────────────────────────────────────────────────


def _extract_table_refs_from_sql(sql: str) -> set[str]:
    """
    Use sqlglot to extract real table references from SQL.
    Falls back to a FROM/JOIN-anchored regex if sqlglot fails.
    Returns lowercased schema.table or bare table strings.
    """
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
    """Lowercased set of schema.table and bare table names from retrieved schemas."""
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
    """
    Return table references in SQL not present in retrieved schemas.
    Uses sqlglot for accurate extraction — no alias.column false positives.
    """
    known = _known_table_refs(schemas)
    found = _extract_table_refs_from_sql(sql)
    return sorted(found - known)


# ─────────────────────────────────────────────────────────────────────────────
# FIX 3 — retry-loop prompt injection
# ─────────────────────────────────────────────────────────────────────────────


def _inject_correction(user_prompt_json: str, hallucinated: list[str]) -> str:
    """
    Re-inject the user prompt with an explicit correction block listing
    every hallucinated table that must not appear in the next attempt.
    """
    parsed = json.loads(user_prompt_json)
    parsed["CorrectionFromPreviousAttempt"] = (
        "YOUR PREVIOUS SQL FAILED VALIDATION.\n"
        "The following table references DO NOT EXIST in AuthoritativeTables "
        "and are FORBIDDEN in your next response:\n"
        + "\n".join(f"  ✗ {t}" for t in hallucinated)
        + "\n\nRewrite the SQL using ONLY tables from AuthoritativeTables. "
        "If a concept cannot be satisfied by any available table, omit it entirely."
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
) -> dict[str, Any]:
    """
    LangGraph node: generate SQL from constructed query + schemas + join paths.

    Consumes:
        state["construct"]["constructed_query"]
        state["retrieved_schemas"]   — list of SchemaResult dicts (with document)
        state["seed_tables"]         — list[str]
        state["join_paths"]          — list[dict | str]

    Produces:
        state["generated_sql"]       — str
        state["token_count"]         — int
        state["token_breakdown"]     — dict
        state["sql_errors"]          — list[str]
        state["hallucinated_tables"] — list[str]
    """
    logger.info("Starting SQL Generator")

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
                f"Retry feedback injected — attempt={attempt}, "
                f"hint={hint[:80]}"
            )

    user_prompt = json.dumps(base_payload, ensure_ascii=False)
    prompt_tokens = _count_tokens(SQL_GENERATION_SYSTEM + user_prompt)
    logger.info(f"Prompt tokens (attempt 1): {prompt_tokens}")

    # ── retry loop ────────────────────────────────────────────────────────────

    result: dict = {}
    sql: str = ""
    hallucinated: list[str] = []
    raw: str = ""

    for attempt in range(MAX_RETRIES + 1):
        logger.info(f"LLM attempt {attempt + 1}/{MAX_RETRIES + 1}")

        try:
            raw = llm.generate(
                system_prompt=SQL_GENERATION_SYSTEM,
                user_prompt=user_prompt,
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

        # FIX 1: accurate detection via sqlglot — no alias.column noise
        hallucinated = _detect_hallucinated_tables(sql, schemas)

        if not hallucinated:
            logger.info(f"No hallucinations detected on attempt {attempt + 1}.")
            break

        logger.warning(f"Attempt {attempt + 1}: hallucinated tables: {hallucinated}")

        if attempt < MAX_RETRIES:
            # FIX 3: inject forbidden table list into next prompt
            user_prompt = _inject_correction(user_prompt, hallucinated)
            logger.info("Correction block injected. Retrying...")
        else:
            return _fail(
                f"Hallucinated tables persist after {MAX_RETRIES + 1} attempts: {hallucinated}"
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
        "hallucinated_tables": hallucinated,
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

    print(f"\n{'='*70}\nFINAL OUTPUT\n{'='*70}")
    print(f"Generated SQL:\n{output.sql}")
    print(f"\n{'='*70}\n")

    return final_state


# ─────────────────────────────────────────────────────────────────────────────
# Workflow helper
# ─────────────────────────────────────────────────────────────────────────────


def run_schema_and_sql_workflow(
    llm: BaseLLM,
    user_query: str,
    domain_context: str = "general",
) -> dict[str, Any]:
    """schema_fetcher_node → sql_generator_node end-to-end."""
    from pathlib import Path

    from src.agent.sub_agent.schema_agent import schema_fetcher_node
    from src.knowledgebase.stores.indexer import Indexer, SchemaType

    logger.info(f"Workflow: {user_query[:60]}...")

    schema_file = (
        Path(__file__).parent.parent.parent
        / "assets"
        / "schema"
        / "AdventureWorksLT2019_schema.json"
    )
    if schema_file.exists():
        try:
            count = Indexer().index_json_from_file(
                schema_type=SchemaType.TABLE, json_path=str(schema_file)
            )
            logger.info(f"Indexed {count} tables")
        except Exception as exc:
            logger.warning(f"Indexing failed: {exc}")

    state: dict[str, Any] = {
        "user_query": user_query,
        "domain_context": domain_context,
        "construct": {
            "constructed_query": user_query,
            "reasoning": "Direct user query for SQL generation",
        },
    }

    logger.info("Step 1: Schema Fetcher")
    state = schema_fetcher_node(state, top_k=5, run_bfs=True)
    logger.info(f"  seed_tables={state.get('seed_tables', [])}")
    logger.info(f"  join_paths={len(state.get('join_paths', []))}")

    logger.info("Step 2: SQL Generator")
    state = sql_generator_node(llm, state)
    logger.info(f"  sql={state.get('generated_sql', '')[:80]}...")
    logger.info(f"  hallucinated_tables={state.get('hallucinated_tables', [])}")

    return state


# # ─────────────────────────────────────────────────────────────────────────────
# # Entrypoint
# # ─────────────────────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     logging.basicConfig(
#         level=logging.INFO,
#         format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#     )

#     from src.agent.llm.registry import get_llm

#     try:
#         model = "meta-llama/llama-4-scout-17b-16e-instruct"
#         llm = get_llm(model_name=model)
#     except Exception as exc:
#         logger.error(f"Failed to initialize LLM: {exc}")
#         exit(1)

#     user_query = (
#         "create me a SQL query to find the top 10 best-selling products in the last 3 years, "
#         "including their category and subcategory, total quantity sold, total revenue generated, "
#         "average selling price, number of distinct customers who bought them, and the best sales "
#         "territory for each product. Use the saleslt schema."
#     )

#     final_state = run_schema_and_sql_workflow(
#         llm=llm, user_query=user_query, domain_context="retail / ecommerce"
#     )

#     print(f"\n{'='*70}\nUSER QUERY\n{'='*70}\n{user_query}")
#     print(
#         f"\n{'='*70}\nGENERATED SQL\n{'='*70}\n{final_state.get('generated_sql', '')}"
#     )
#     print(f"\n{'='*70}\nSEED TABLES\n{'='*70}\n{final_state.get('seed_tables', [])}")
#     print(f"\n{'='*70}\nHALLUCINATED TABLES\n{'='*70}")
#     print(json.dumps(final_state.get("hallucinated_tables", []), indent=2))
#     print(f"\n{'='*70}\nERRORS\n{'='*70}")
#     errors = final_state.get("sql_errors", [])
#     print(json.dumps(errors, indent=2) if errors else "None")
#     print(f"\n{'='*70}\nTOKEN BREAKDOWN\n{'='*70}")
#     print(json.dumps(final_state.get("token_breakdown", {}), indent=2))
