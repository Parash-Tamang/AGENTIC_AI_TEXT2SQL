"""
Schema Agent — refactored for BFS-first table discovery.

Pipeline inside this node:
  1. Semantic fetch (once)     : fetch_schema via vector similarity to get initial
                                 candidate schemas from constructed + sub queries.
  2. LLM seed filter           : agent reads views structural_signals + candidate
                                 schemas and extracts precise seed tables, dropping
                                 noise.  JSON contract mirrors query_refiner.
  3. BFS join discovery        : deterministic graph traversal from seeds → finds
                                 missing tables + valid join paths. No LLM involved.
  4. Dynamic WHERE fetch       : for every BFS-discovered table not already in
                                 retrieved schemas, call fetch_schema with
                                 table_name=<exact> (metadata filter, no embedding).
                                 ChromaDB WHERE clause — fast, zero ambiguity.
  5. State write               : retrieved_schemas, seed_tables, join_paths ready
                                 for sql_generator_node.

executor.py is untouched — all tool calls go through dispatch() as before.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM
from src.agent.llm.registry import get_llm
from src.agent.prompt.schema_agent import (
    SCHEMA_SEED_FILTER_SYSTEM,
    SCHEMA_SUFFICIENCY_SYSTEM,
)
from src.agent.tools.executor import dispatch, SchemaResult
from src.agent.utils.pretty_print import pretty_log
from src.agent.utils.prompt_utils import resolve_system_prompt
from src.models.permission_context import get_permission_context

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MAX_WORKERS = 1  # SQLite: no concurrent writes; bump for Postgres
DEFAULT_TOP_K = 5  # schemas per semantic query
MAX_BFS_HOPS = 2  # depth 2 covers most real queries; 3+ adds noise
MAX_BFS_FILTER_DEPTH = 3  # agent can request depth-3 on retry
MAX_SCHEMA_SUFFICIENCY_RETRIES = 3


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ─────────────────────────────────────────────────────────────────────────────


class SeedFilterResult(BaseModel):
    seed_tables: list[str] = Field(default_factory=list)
    reasoning: str = ""
    requested_bfs_depth: int = MAX_BFS_HOPS


class FetchError(BaseModel):
    query: str
    error: str


class SchemaCoverageResult(BaseModel):
    is_sufficient: bool = True
    missing_tables: list[str] = Field(default_factory=list)
    reasoning: str = ""


class SchemasState(BaseModel):
    """
    Validated container for everything schema_fetcher writes into state["schemas"].
    Identical shape to before — downstream nodes see the same dict structure.
    """

    schemas: list[SchemaResult] = Field(default_factory=list)
    unique_count: int = 0
    query_map: dict[str, list[str]] = Field(default_factory=dict)
    errors: list[FetchError] = Field(default_factory=list)

    def add_schema(self, query: str, schema: SchemaResult) -> None:
        name = schema.qualified_name
        existing = next((s for s in self.schemas if s.qualified_name == name), None)
        if existing is None:
            schema.source_queries = [query]
            self.schemas.append(schema)
            self.unique_count += 1
        else:
            if query not in existing.source_queries:
                existing.source_queries.append(query)
        self.query_map.setdefault(query, [])
        if name not in self.query_map[query]:
            self.query_map[query].append(name)

    def add_error(self, query: str, error: str) -> None:
        self.errors.append(FetchError(query=query, error=error))

    def has_table(self, table_name: str) -> bool:
        return any(s.table_name == table_name for s in self.schemas)

    def serializable(self) -> dict:
        return {
            "schemas": [s.model_dump() for s in self.schemas],
            "unique_count": self.unique_count,
            "query_map": self.query_map,
            "errors": [e.model_dump() for e in self.errors],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_llm_json(raw: str) -> dict:
    """Strip markdown fences, parse JSON. Mirrors query_refiner pattern."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    return json.loads(cleaned)


def _as_list_or_dict(raw: Any) -> Any:
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return raw


def _resolve_allowed_table_names(user_role: str | None) -> list[str]:
    """Resolve RBAC allowlist as unqualified table names for vector-store $in filters."""
    if not user_role:
        return []
    try:
        allowed = get_permission_context(user_role).allowed_tables()
        # permissions.json stores qualified names like SalesLT.Customer; metadata table_name is bare.
        return sorted({str(t).split(".")[-1] for t in allowed if str(t).strip()})
    except Exception as exc:
        logger.warning(
            "Could not resolve RBAC allowlist for role '%s': %s", user_role, exc
        )
        return []


def _get_all_queries(state: dict[str, Any]) -> list[str]:
    """
    Unique non-empty queries from state.
    Same extraction logic as views_agent for consistency.
    """
    candidates: list[str] = []
    construct = state.get("construct", {})
    if isinstance(construct, str):
        try:
            construct = json.loads(construct)
        except json.JSONDecodeError:
            construct = {}
    elif hasattr(construct, "model_dump"):
        construct = construct.model_dump()
    if not isinstance(construct, dict):
        construct = {}

    constructed = construct.get("constructed_query", "")
    if constructed:
        candidates.append(constructed)
    decomposed = state.get("decomposed", {})
    if isinstance(decomposed, str):
        try:
            decomposed = json.loads(decomposed)
        except json.JSONDecodeError:
            decomposed = {}
    elif hasattr(decomposed, "model_dump"):
        decomposed = decomposed.model_dump()
    if not isinstance(decomposed, dict):
        decomposed = {}

    if decomposed.get("is_composite"):
        for sub_q in decomposed.get("sub_queries", []):
            q = (
                sub_q.get("query", "")
                if isinstance(sub_q, dict)
                else getattr(sub_q, "query", "")
            )
            if q:
                candidates.append(q)
    seen: set[str] = set()
    return [q for q in candidates if q not in seen and not seen.add(q)]  # type: ignore[func-returns-value]


def _run_schema_sufficiency_check(
    llm: BaseLLM,
    user_query: str,
    schemas: list[SchemaResult],
    join_paths: list[dict] | list[str],
    system_prompt: str,
) -> SchemaCoverageResult:
    """LLM coverage check over final schemas + join paths."""
    if not schemas:
        return SchemaCoverageResult(
            is_sufficient=False,
            missing_tables=[],
            reasoning="No schemas available for validation.",
        )

    schemas_brief = [
        {
            "table_name": s.table_name,
            "qualified_name": s.qualified_name,
            "doc": (s.document or "")[:220],
        }
        for s in schemas
    ]

    user_prompt = (
        f"UserQuery: {user_query}\n\n"
        f"FinalSchemas: {json.dumps(schemas_brief, ensure_ascii=True)}\n\n"
        f"JoinPaths: {json.dumps(join_paths, ensure_ascii=True)}\n\n"
        "Validate schema coverage and return JSON only."
    )

    try:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "schema_coverage",
                "schema": SchemaCoverageResult.model_json_schema(),
            },
        }

        raw = llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
            json_mode=True,
        )

        if isinstance(raw, (dict, list)):
            data = raw if isinstance(raw, dict) else raw[0]
        else:
            data = _parse_llm_json(raw)
        missing = [
            str(t).strip() for t in data.get("missing_tables", []) if str(t).strip()
        ]
        # Normalize qualified table names to unqualified for fetch/filter consistency.
        missing = [m.split(".")[-1] for m in missing]
        return SchemaCoverageResult(
            is_sufficient=bool(data.get("is_sufficient", True)),
            missing_tables=sorted(set(missing)),
            reasoning=str(data.get("reasoning", "")),
        )
    except Exception as exc:
        logger.error(f"Schema sufficiency check LLM error: {exc}")
        # Fail open: avoid blocking the pipeline when validator fails.
        return SchemaCoverageResult(
            is_sufficient=True,
            missing_tables=[],
            reasoning=f"Validator failed: {exc}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Semantic fetch (once, same as before)
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_schemas_for_query(
    query: str, top_k: int, allowed_table_names: list[str] | None = None
) -> tuple[str, list[SchemaResult]]:
    """Fetch + validate schemas for one query."""
    try:
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if allowed_table_names:
            payload["table_names"] = allowed_table_names
        raw = dispatch("fetch_schema", payload)
        raw_list = _as_list_or_dict(raw)
        if isinstance(raw_list, dict):
            if "error" in raw_list:
                logger.warning(
                    f"fetch_schema error '{query[:50]}': {raw_list['error']}"
                )
                return query, []
            raw_list = [raw_list]
        if not isinstance(raw_list, list):
            logger.error(
                f"fetch_schema returned unsupported type {type(raw_list).__name__} for '{query[:50]}'"
            )
            return query, []
        if isinstance(raw_list, dict) and "error" in raw_list:
            logger.warning(f"fetch_schema error '{query[:50]}': {raw_list['error']}")
            return query, []
        results: list[SchemaResult] = []
        for item in raw_list:
            if "error" in item:
                continue
            try:
                results.append(SchemaResult(**item))
            except Exception as exc:
                logger.warning(f"SchemaResult validation failed: {exc}")
        logger.debug(f"Fetched {len(results)} schemas for '{query[:50]}'")
        return query, results
    except Exception as exc:
        logger.error(f"Exception fetching schemas for '{query[:50]}': {exc}")
        return query, []


def _run_semantic_fetch(
    queries: list[str], top_k: int, allowed_table_names: list[str] | None = None
) -> SchemasState:
    """Sequential fetch (MAX_WORKERS=1 for SQLite safety, ready for Postgres bump)."""
    state = SchemasState()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_fetch_schemas_for_query, q, top_k, allowed_table_names): q
            for q in queries
        }
        for future in as_completed(futures):
            query = futures[future]
            try:
                _, schemas = future.result()
                for schema in schemas:
                    state.add_schema(query, schema)
            except Exception as exc:
                state.add_error(query, str(exc))
                logger.error(f"Future error '{query[:50]}': {exc}")
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — LLM seed filter
# ─────────────────────────────────────────────────────────────────────────────


def _run_seed_filter(
    llm: BaseLLM,
    constructed_query: str,
    structural_signals: list[str],
    schemas: list[SchemaResult],
    system_prompt: str,
) -> SeedFilterResult:
    """
    LLM agent reads views structural_signals + candidate schemas and returns
    precise seed tables for BFS. Drops noise (audit, archive, irrelevant lookups).

    Prompt is intentionally short — only table names + one-line descriptions,
    NOT full schema documents. Full docs are fetched after BFS confirms the table.
    """
    if not schemas:
        return SeedFilterResult()

    # Compact candidate list — name + first 120 chars of document
    candidates_text = "\n".join(
        f"- {s.table_name}: {s.document[:120].strip()}" for s in schemas
    )
    signals_text = ", ".join(structural_signals) if structural_signals else "none"

    user_prompt = (
        f"ConstructedQuery: {constructed_query}\n\n"
        f"StructuralSignals: {signals_text}\n\n"
        f"CandidateTables:\n{candidates_text}\n\n"
        "Extract seed tables for BFS traversal."
    )

    try:
        # Request structured JSON output using the SeedFilterResult pydantic model
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "seed_filter_result",
                "schema": SeedFilterResult.model_json_schema(),
            },
        }

        raw = llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
            json_mode=True,
        )

        # llm.generate may return a dict when json_mode=True; handle both cases
        if isinstance(raw, (dict, list)):
            data = raw
        else:
            data = _parse_llm_json(raw)

        seed_tables = [
            t
            for t in data.get("seed_tables", [])
            # Safety: only keep tables that actually exist in candidates
            if any(s.table_name == t for s in schemas)
        ]
        depth = int(data.get("requested_bfs_depth", MAX_BFS_HOPS))
        depth = max(2, min(3, depth))  # clamp to [2, 3]

        result = SeedFilterResult(
            seed_tables=seed_tables,
            reasoning=data.get("reasoning", ""),
            requested_bfs_depth=depth,
        )
        logger.info(
            f"Seed filter: {len(seed_tables)} seeds, BFS depth={depth} — {seed_tables}"
        )
        return result

    except Exception as exc:
        logger.error(f"Seed filter LLM error: {exc}")
        # Fallback: use all candidate table names as seeds
        fallback = sorted({s.table_name for s in schemas if s.table_name != "unknown"})
        logger.warning(f"Seed filter fallback to all {len(fallback)} candidates")
        return SeedFilterResult(seed_tables=fallback)


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — BFS join discovery (deterministic, no LLM)
# ─────────────────────────────────────────────────────────────────────────────


def _run_bfs(seed_tables: list[str], max_hops: int) -> tuple[list[dict], list[str]]:
    """
    BFS over pre-loaded FK graph via executor dispatch.
    Returns (join_paths, all_discovered_table_names).
    """
    if len(seed_tables) < 2:
        logger.debug("Skipping BFS — fewer than 2 seed tables")
        return [], seed_tables

    logger.info(f"BFS: seeds={seed_tables}, max_hops={max_hops}")
    try:
        raw = dispatch("bfs_join", {"seed_tables": seed_tables, "max_hops": max_hops})
        result: dict = json.loads(raw)
        join_paths: list[dict] = result.get("joins", [])
        # BFS result also carries tables it traversed — extract them
        discovered: list[str] = result.get("tables", seed_tables)
        logger.info(
            f"BFS discovered {len(discovered)} tables, {len(join_paths)} join paths"
        )
        return join_paths, discovered
    except Exception as exc:
        logger.error(f"BFS failed: {exc}")
        return [], seed_tables


# ─────────────────────────────────────────────────────────────────────────────
# Step 4 — Dynamic WHERE fetch for BFS-discovered missing tables
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_missing_tables(
    discovered_tables: list[str],
    schemas_state: SchemasState,
    allowed_table_names: list[str] | None = None,
) -> list[SchemaResult]:
    """
    For each BFS-discovered table not already in schemas_state, fetch its full
    schema using exact metadata filter (table_name=<name>) — no embedding needed.

    This is the WHERE clause fetch: ChromaDB metadata filter, not vector similarity.
    Fast, precise, zero hallucination risk.
    """
    normalized = [
        str(t).strip().split(".")[-1] for t in discovered_tables if str(t).strip()
    ]
    allowed_set = set(allowed_table_names or [])
    if allowed_set:
        normalized = [t for t in normalized if t in allowed_set]

    missing = [t for t in normalized if not schemas_state.has_table(t)]
    if not missing:
        logger.debug("No missing tables — all BFS tables already fetched")
        return []

    logger.info(f"Dynamic WHERE fetch for {len(missing)} missing tables: {missing}")
    fetched: list[SchemaResult] = []

    for table_name in missing:
        try:
            # Pass table_name as exact filter — executor passes it to
            # vector_store.query_schemas(table_name=<name>) which translates
            # to a ChromaDB WHERE {"table_name": {"$eq": table_name}} filter.
            raw = dispatch(
                "fetch_schema",
                {
                    "query": table_name,  # minimal query — exact filter does the work
                    "table_name": table_name,  # ChromaDB WHERE clause
                    "table_names": allowed_table_names
                    or [],  # ChromaDB WHERE table_name $in [...]
                    "top_k": 1,  # only need the one exact match
                },
            )
            results = _as_list_or_dict(raw)
            if isinstance(results, dict):
                results = [results]
            if not isinstance(results, list):
                logger.error(
                    f"fetch_schema returned unsupported type {type(results).__name__} for WHERE fetch '{table_name}'"
                )
                continue
            for item in results:
                if "error" not in item:
                    schema = SchemaResult(**item)
                    fetched.append(schema)
                    logger.debug(f"WHERE fetch: got {schema.qualified_name}")
        except Exception as exc:
            logger.error(f"WHERE fetch failed for '{table_name}': {exc}")

    logger.info(f"WHERE fetch completed: {len(fetched)} additional schemas retrieved")
    return fetched


# ─────────────────────────────────────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────────────────────────────────────


def schema_fetcher_node(
    llm: BaseLLM,
    state: dict[str, Any],
    top_k: int = DEFAULT_TOP_K,
    run_bfs: bool = True,
) -> dict[str, Any]:
    """
    LangGraph node: fetch schemas via BFS-first discovery pipeline.

    Steps:
      1. Semantic fetch   — vector similarity for initial candidate schemas.
      2. LLM seed filter  — agent extracts precise seeds using views structural
                            signals + candidate table descriptions. No full docs
                            in prompt — keeps token use minimal.
      3. BFS traversal    — deterministic FK graph walk, finds missing tables
                            and join paths. No LLM involved.
      4. WHERE fetch      — exact metadata filter for BFS-discovered tables not
                            in initial fetch. Fast, no embedding, no ambiguity.

    State keys written (same shape as before — downstream nodes unchanged):
        state["schemas"]           : SchemasState serialized dict
        state["retrieved_schemas"] : list[SchemaResult dicts] for sql_generator
        state["seed_tables"]       : list[str] filtered seeds from LLM agent
        state["join_paths"]        : list[dict] from BFS

    Args:
        state:   LangGraph state (must have construct, decomposed, views_grade).
        llm:     BaseLLM instance. If None, resolved from registry.
        top_k:   Schemas per semantic query.
        run_bfs: Set False to skip BFS (e.g. simple single-table queries).
    """
    logger.info("Schema agent starting (BFS-first pipeline)")

    # ── Resolve LLM ──────────────────────────────────────────────────────────
    if llm is None:
        try:
            llm = get_llm()
        except Exception as exc:
            logger.error(f"LLM registry error: {exc}")
            empty = SchemasState()
            empty.add_error("", f"LLM unavailable: {exc}")
            return {
                **state,
                "schemas": empty.serializable(),
                "retrieved_schemas": [],
                "seed_tables": [],
                "join_paths": [],
            }

    queries = _get_all_queries(state)
    allowed_table_names = _resolve_allowed_table_names(state.get("user_role"))
    if allowed_table_names:
        logger.info(
            "Applying RBAC table allowlist (%d) for schema retrieval",
            len(allowed_table_names),
        )
    constructed_query = state.get("construct", {}).get("constructed_query", "")
    user_query_for_validation = (
        constructed_query or state.get("refined_query") or state.get("user_query", "")
    )

    if not queries:
        logger.error("No queries in state")
        empty = SchemasState()
        empty.add_error("", "No queries found in state")
        return {
            **state,
            "schemas": empty.serializable(),
            "retrieved_schemas": [],
            "seed_tables": [],
            "join_paths": [],
        }

    logger.info(f"Schema fetch for {len(queries)} queries")

    # ── Step 1: semantic fetch ────────────────────────────────────────────────
    schemas_state = _run_semantic_fetch(queries, top_k, allowed_table_names)
    logger.info(f"Semantic fetch: {schemas_state.unique_count} unique schemas")

    # Always expose coverage keys in state, even when validation cannot run.
    state["schema_coverage"] = {}
    state["schema_coverage_history"] = []

    seed_tables: list[str] = []
    join_paths: list[dict] = []

    if run_bfs and schemas_state.schemas:
        seed_filter_prompt = resolve_system_prompt(
            state, "schema_seed_filter", SCHEMA_SEED_FILTER_SYSTEM
        )
        sufficiency_prompt = resolve_system_prompt(
            state, "schema_sufficiency", SCHEMA_SUFFICIENCY_SYSTEM
        )

        # ── Step 2: LLM seed filter ───────────────────────────────────────────
        # Read structural signals that views_agent extracted in role 1
        structural_signals: list[str] = state.get("views_grade", {}).get(
            "structural_signals", []
        )
        filter_result = _run_seed_filter(
            llm=llm,
            constructed_query=constructed_query,
            structural_signals=structural_signals,
            schemas=schemas_state.schemas,
            system_prompt=seed_filter_prompt,
        )
        seed_tables = filter_result.seed_tables
        bfs_depth = filter_result.requested_bfs_depth

        if seed_tables:
            # ── Step 3: BFS join discovery ────────────────────────────────────
            join_paths, discovered_tables = _run_bfs(seed_tables, bfs_depth)

            # ── Step 4: WHERE fetch for missing tables ────────────────────────
            missing_schemas = _fetch_missing_tables(
                discovered_tables, schemas_state, allowed_table_names
            )
            for schema in missing_schemas:
                # Register under constructed_query as source
                schemas_state.add_schema(f"bfs:{schema.table_name}", schema)

            # ── Step 5: LLM sufficiency validation + retry fetch (max 3) ─────
            coverage_history: list[dict[str, Any]] = []
            for attempt in range(1, MAX_SCHEMA_SUFFICIENCY_RETRIES + 1):
                coverage = _run_schema_sufficiency_check(
                    llm=llm,
                    user_query=user_query_for_validation,
                    schemas=schemas_state.schemas,
                    join_paths=join_paths,
                    system_prompt=sufficiency_prompt,
                )
                coverage_history.append({"attempt": attempt, **coverage.model_dump()})

                if coverage.is_sufficient:
                    logger.info(
                        f"Schema sufficiency passed on attempt {attempt}: {coverage.reasoning}"
                    )
                    break

                if not coverage.missing_tables:
                    logger.warning(
                        f"Schema sufficiency failed on attempt {attempt} but no missing tables returned"
                    )
                    break

                logger.info(
                    f"Schema sufficiency retry {attempt}: fetching missing tables {coverage.missing_tables}"
                )
                retry_schemas = _fetch_missing_tables(
                    coverage.missing_tables, schemas_state, allowed_table_names
                )
                if not retry_schemas:
                    logger.warning(
                        f"Schema sufficiency retry {attempt}: no additional schemas fetched"
                    )
                    break

                for schema in retry_schemas:
                    schemas_state.add_schema(f"retry:{schema.table_name}", schema)

            state["schema_coverage"] = coverage_history[-1] if coverage_history else {}
            state["schema_coverage_history"] = coverage_history

        else:
            logger.warning("Seed filter returned no seeds — skipping BFS")

    elif not run_bfs:
        # Fallback: extract seeds without BFS (simple queries)
        seed_tables = sorted(
            {s.table_name for s in schemas_state.schemas if s.table_name != "unknown"}
        )
        logger.info(f"BFS skipped — {len(seed_tables)} seeds from semantic fetch only")

    logger.info(
        f"Schema agent complete: {schemas_state.unique_count} schemas, "
        f"{len(seed_tables)} seeds, {len(join_paths)} join paths"
    )

    # If we found no schemas, signal the pipeline to generate a clarification
    # response rather than attempting SQL generation. This keeps the short-
    # circuit logic inside the schema agent as requested by the caller.
    if schemas_state.unique_count == 0:
        clarify_hint = (
            "I couldn't find any database schema information to run this request. "
            "Please specify which table or fields you want to query, or provide a bit more detail about the data you're after."
        )
        state = {
            **state,
            "intent": {
                "intent": "NEEDS_CLARITY",
                "route_to": "Generate",
                "confidence": 1.0,
                "output_format": "NL",
                "graph_type": None,
                "excel_marker": False,
                "reasoning": "No schemas found — requesting clarification.",
            },
            "clarify_hint": clarify_hint,
            # still include empty schema outputs for downstream compatibility
            "schemas": schemas_state.serializable(),
            "retrieved_schemas": [],
            "seed_tables": seed_tables,
            "join_paths": join_paths,
        }

        return state

    # Pretty print concise summary
    pretty_log(
        "SchemaFetcher",
        state={
            "user_query": user_query_for_validation,
            "constructed_query": constructed_query,
        },
        llm_metrics={"token_breakdown": {}, "latency_ms": None},
        extra={
            "schemas": schemas_state.unique_count,
            "seeds": seed_tables,
            "join_paths": len(join_paths),
        },
    )

    return {
        **state,
        "schemas": schemas_state.serializable(),
        "retrieved_schemas": [s.model_dump() for s in schemas_state.schemas],
        "seed_tables": seed_tables,
        "join_paths": join_paths,
    }
