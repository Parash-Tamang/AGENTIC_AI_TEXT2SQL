"""
Tool executor — abstracts connection details from the LLM.
Imports only from config.py and external packages — never from this package root.
"""

from __future__ import annotations

import json
from typing import Any

from src.database.executor import (
    execute_query as _execute_query,
    execute_view as _execute_view,
)
from pydantic import BaseModel, Field
from src.agent.tools.config import ConnectionConfig
from src.agent.utils.pretty_print import pretty_log
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Connection helper — reads from state, falls back to global singleton
# ─────────────────────────────────────────────────────────────────────────────


def _get_conn_from_state(state: dict) -> "ConnectionConfig":
    if state.get("server") and state.get("database"):
        return ConnectionConfig(
            db_type=state.get("db_type", "mssql"),
            server=state["server"],
            database=state["database"],
            username=state.get("username"),
            password=state.get("password"),
            port=state.get("port"),
            pool_size=state.get("pool_size", 5),
            timeout=state.get("timeout", 30),
        )
    from src.agent.tools.config import get_connection_config

    return get_connection_config()


# ─────────────────────────────────────────────────────────────────────────────
# Graph Cache
# ─────────────────────────────────────────────────────────────────────────────

_GRAPH_CACHE: dict[str, Any] = {}


def _get_or_load_graph(db_id: str) -> Any:
    if db_id in _GRAPH_CACHE:
        print(f"   📦 Using cached graph for {db_id}")
        return _GRAPH_CACHE[db_id]

    print(f"   📚 Loading graph for {db_id}...")
    from src.knowledgebase.config.graph_setting import graph_manager

    graph_manager.load_one(db_id)
    graph = graph_manager.get_graph(db_id)
    _GRAPH_CACHE[db_id] = graph
    print(
        f"   ✅ Graph loaded: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
    )
    return graph


def _normalize_execution_result(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        nested = result.get("execution_result")
        if isinstance(nested, dict):
            result = nested
        if "rowcount" in result or "rows" in result or "error" in result:
            rows = result.get("rows") or []
            rowcount = result.get("rowcount")
            if rowcount is None and isinstance(rows, list):
                rowcount = len(rows)
            normalized = dict(result)
            normalized["rows"] = rows if isinstance(rows, list) else []
            normalized["rowcount"] = int(rowcount or 0)
            normalized.setdefault("error", None)
            return normalized

    if isinstance(result, pd.DataFrame) or hasattr(result, "shape"):
        df = result if isinstance(result, pd.DataFrame) else pd.DataFrame(result)
        return {
            "type": "DataFrame",
            "shape": list(df.shape),
            "rows": df.head(50).to_dict(orient="records"),
            "sample_rows": df.head(20).to_dict(orient="records"),
            "rowcount": int(df.shape[0]),
            "error": None,
        }

    if result is None:
        return {"rows": [], "rowcount": 0, "error": None}

    return {"rows": [], "rowcount": 0, "error": None, "raw": str(result)}


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic result models
# ─────────────────────────────────────────────────────────────────────────────


class SchemaResult(BaseModel):
    database_name: str = ""
    schema_name: str = ""
    table_name: str = ""
    type: str = "table"
    document: str = ""
    distance: float = Field(default=1.0, ge=0.0)
    source_queries: list[str] = Field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        if self.schema_name and self.table_name:
            return f"{self.schema_name}.{self.table_name}"
        return self.table_name or "unknown"


class ViewResult(BaseModel):
    database_name: str = ""
    schema_name: str = ""
    view_name: str = ""
    type: str = "view"
    document: str = ""
    distance: float = Field(default=1.0, ge=0.0)
    source_queries: list[str] = Field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        if self.schema_name and self.view_name:
            return f"{self.schema_name}.{self.view_name}"
        return self.view_name or "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Handlers
# ─────────────────────────────────────────────────────────────────────────────


def _handle_execute_query(inputs: dict, state: dict) -> dict:
    conn = _get_conn_from_state(state)
    print(f"   🔍 SQL: {inputs['sql'][:120]}...")
    result = _execute_query(
        sql=inputs["sql"],
        db_type=conn.db_type,
        server=conn.server,
        database=conn.database,
        username=conn.username,
        password=conn.password,
        port=conn.port,
        pool_size=conn.pool_size,
        timeout=conn.timeout,
        max_rows=inputs.get("max_rows", 100),
        expected_columns=inputs.get("expected_columns"),
    )  # already a dict or DataFrame

    try:
        summary = _normalize_execution_result(result)

        # Use summary for terminal prints and later state
        rowcount = summary.get("rowcount")
        error = summary.get("error")
        sample = summary.get("sample_rows") or (summary.get("rows") or [])[:3]

        print(f"   🔍 execution_result: rows={rowcount}, error={error}")
        if sample:
            print(f"      sample_rows: {sample}")
        pretty_log(
            "executor",
            state={"generated_sql": inputs["sql"]},
            llm_metrics={"token_breakdown": {}},
            extra={"execution_result": summary},
        )

        # Replace result with normalized summary for downstream consumers
        result = summary
    except Exception as exc:
        print(f"   🔍 execution_result: ERROR - {exc}")
        result = {"rows": [], "rowcount": 0, "error": str(exc)}

    return result


def _handle_execute_view(inputs: dict, state: dict) -> dict:
    conn = _get_conn_from_state(state)
    return _execute_view(
        view_name=inputs["view_name"],
        db_type=conn.db_type,
        server=conn.server,
        database=conn.database,
        username=conn.username,
        password=conn.password,
        port=conn.port,
        pool_size=conn.pool_size,
        timeout=conn.timeout,
        schema=inputs.get("schema"),
        max_rows=inputs.get("max_rows", 100),
        expected_columns=inputs.get("expected_columns"),
    )


def _handle_fetch_schema(inputs: dict, state: dict) -> list[dict]:
    from src.knowledgebase.stores.vector_store import VectorStore
    from src.knowledgebase.stores.embedder import Embedder

    conn = _get_conn_from_state(state)

    try:
        vector_store = VectorStore()
        embedder = Embedder()

        print(f"   📥 fetch_schema query='{inputs['query']}' db='{conn.database}'")
        embedding = embedder.embed(inputs["query"])
        raw_results = vector_store.query_schemas(
            embedding=embedding,
            database_name=conn.database,
            top_k=inputs.get("top_k", 5),
            schema_name=inputs.get("schema_name"),
            table_name=inputs.get("table_name"),
        )

        results = []
        for item in raw_results:
            schema = SchemaResult(
                **item.get("metadata", {}),
                document=item.get("document", ""),
                distance=item.get("distance", 1.0),
            )
            results.append(schema.model_dump())

        print(f"   📤 fetch_schema returned {len(results)} results")
        return results

    except Exception as exc:
        print(f"   ❌ fetch_schema error: {exc}")
        return [{"error": str(exc)}]


def _handle_fetch_view(inputs: dict, state: dict) -> list[dict]:
    from src.knowledgebase.stores.vector_store import VectorStore
    from src.knowledgebase.stores.embedder import Embedder

    conn = _get_conn_from_state(state)

    try:
        vector_store = VectorStore()
        embedder = Embedder()

        print(f"   📥 fetch_view query='{inputs['query']}' db='{conn.database}'")
        embedding = embedder.embed(inputs["query"])
        raw_results = vector_store.query_views(
            embedding=embedding,
            database_name=conn.database,
            top_k=inputs.get("top_k", 5),
            schema_name=inputs.get("schema_name"),
            view_name=inputs.get("view_name"),
        )

        results = []
        for item in raw_results:
            view = ViewResult(
                **item.get("metadata", {}),
                document=item.get("document", ""),
                distance=item.get("distance", 1.0),
            )
            results.append(view.model_dump())

        print(f"   📤 fetch_view returned {len(results)} results")
        return results

    except Exception as exc:
        print(f"   ❌ fetch_view error: {exc}")
        return [{"error": str(exc)}]


def _handle_bfs_join(inputs: dict, state: dict) -> dict:
    from src.knowledgebase.graph.search_graph import bfs_schema_with_joins as _bfs

    conn = _get_conn_from_state(state)
    db_id = conn.database

    seed_tables = inputs.get("seed_tables", [])
    max_hops = inputs.get("max_hops", 2)
    token_limit = inputs.get("token_limit", 8000)

    print(f"   📥 bfs_join seeds={seed_tables}, db={db_id}")
    graph = _get_or_load_graph(db_id)
    result = _bfs(
        graph=graph, seed_tables=seed_tables, max_hops=max_hops, token_limit=token_limit
    )
    print(f"   📤 bfs_join discovered {len(result.get('tables', []))} tables")
    return result


def _handle_grade_views(inputs: dict, state: dict) -> dict:
    query = inputs.get("query", "")
    view_names = inputs.get("view_names", [])
    view_docs = inputs.get("view_docs", [])

    print(f"   📥 grade_views query='{query[:50]}...' views={len(view_names)}")

    if not view_names or not view_docs:
        return {
            "answer": "no",
            "confidence": 0.0,
            "reasoning": "No views available to grade",
        }

    query_lower = query.lower()
    view_text = " ".join(view_docs).lower()

    categories = {
        "customer": {
            "keywords": ["customer", "clients", "users", "account", "person"],
            "weight": 0.25,
        },
        "order": {
            "keywords": ["order", "purchase", "transaction", "sale", "detail"],
            "weight": 0.25,
        },
        "product": {"keywords": ["product", "item", "good", "sku"], "weight": 0.20},
        "category": {
            "keywords": ["category", "classification", "type", "group"],
            "weight": 0.15,
        },
        "data": {"keywords": ["date", "time", "recorded", "timestamp"], "weight": 0.15},
    }

    total_score = 0.0
    matched_categories = 0
    for cat_info in categories.values():
        if any(kw in query_lower for kw in cat_info["keywords"]) and any(
            kw in view_text for kw in cat_info["keywords"]
        ):
            total_score += cat_info["weight"]
            matched_categories += 1

    answer = "yes" if total_score >= 0.5 else "no"
    reasoning = (
        f"Coverage: {matched_categories}/{len(categories)} categories matched. "
        f"Confidence: {total_score:.2f}. Views: {', '.join(view_names[:3])}"
    )

    print(f"   📤 grade_views answer={answer} confidence={total_score:.2f}")
    return {"answer": answer, "confidence": total_score, "reasoning": reasoning}


def _handle_check_sufficiency(inputs: dict, state: dict) -> dict:
    query = inputs.get("query", "")
    view_names = inputs.get("view_names", [])

    print(f"   📥 check_sufficiency query='{query[:50]}...' views={len(view_names)}")

    if not view_names:
        return {
            "is_sufficient": False,
            "confidence": 0.0,
            "reasoning": "No views available",
        }

    query_lower = query.lower()
    view_text = " ".join(view_names).lower()

    categories = {
        "customer": ["customer", "clients", "users", "account"],
        "order": ["order", "purchase", "transaction", "sale"],
        "product": ["product", "item", "good"],
        "category": ["category", "classification", "type"],
    }

    matched_count = sum(
        1
        for keywords in categories.values()
        if any(kw in query_lower for kw in keywords)
        and any(kw in view_text for kw in keywords)
    )

    is_sufficient = matched_count >= 2
    confidence = min(matched_count / len(categories), 1.0)
    reasoning = f"Matched {matched_count}/{len(categories)} categories. Views: {', '.join(view_names[:3])}"

    print(
        f"   📤 check_sufficiency is_sufficient={is_sufficient} confidence={confidence:.2f}"
    )
    return {
        "is_sufficient": is_sufficient,
        "confidence": confidence,
        "reasoning": reasoning,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    "execute_query": _handle_execute_query,
    "execute_view": _handle_execute_view,
    "fetch_schema": _handle_fetch_schema,
    "fetch_view": _handle_fetch_view,
    "bfs_join": _handle_bfs_join,
    "grade_views": _handle_grade_views,
    "check_sufficiency": _handle_check_sufficiency,
}


def dispatch(
    tool_name: str, tool_inputs: str | dict, state: dict | None = None
) -> dict:
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(
            f"Unknown tool '{tool_name}'. Available: {list(_HANDLERS.keys())}"
        )

    if isinstance(tool_inputs, str):
        tool_inputs = json.loads(tool_inputs)

    tool_inputs = {k: v for k, v in tool_inputs.items() if v is not None}

    result = handler(tool_inputs, state or {})

    # Always return a dict — never a raw string
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            result = {"raw": result}

    return result


def dispatch_to_tool_result(tool_use_block, state: dict | None = None) -> dict:
    """Anthropic-style tool_result block wrapper."""
    try:
        result = dispatch(tool_use_block.name, tool_use_block.input, state)
        content = json.dumps(result, default=str)  # serialize only here, for the API
        is_error = False
    except Exception as exc:
        content = json.dumps({"error": str(exc)})
        is_error = True

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_block.id,
        "content": content,
        "is_error": is_error,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Node entrypoint — called by GraphEngine
# ─────────────────────────────────────────────────────────────────────────────


def executor_node(state: dict) -> dict:
    import logging

    logger = logging.getLogger(__name__)

    sql = state.get("generated_sql", "").strip()

    if not sql:
        logger.error("executor_node: no generated_sql in state")
        return {
            **state,
            "execution_result": {
                "rows": [],
                "rowcount": 0,
                "error": "No SQL to execute",
            },
        }

    logger.info(f"executor_node: executing SQL ({len(sql)} chars)")

    try:
        result = dispatch("execute_query", {"sql": sql}, state=state)
        result = _normalize_execution_result(result)
        # Print a concise terminal summary of the execution result
        try:
            rowcount = result.get("rowcount")
            error = result.get("error")
            sample_rows = result.get("rows") or result.get("sample_rows") or []
            sample = sample_rows[:3] if isinstance(sample_rows, list) else []

            print(f"   🔍 execution_result: rows={rowcount}, error={error}")
            if sample:
                print(f"      sample_rows: {sample}")
            pretty_log(
                "executor",
                state={"generated_sql": sql},
                llm_metrics={"token_breakdown": {}},
                extra={"execution_result": result},
            )
        except Exception:
            print(f"   🔍 execution_result: {result}")
    except Exception as exc:
        logger.error(f"executor_node: execution failed: {exc}")
        result = {"rows": [], "rowcount": 0, "error": str(exc)}

        # Print error to terminal for visibility
        try:
            print(f"   ❌ execution_error: {result.get('error')}")
            pretty_log(
                "executor",
                state={"generated_sql": sql},
                llm_metrics={"token_breakdown": {}},
                extra={"execution_result": result},
            )
        except Exception:
            pass

    logger.info(
        f"executor_node: done — "
        f"rowcount={result.get('rowcount', 0)}, "
        f"error={result.get('error')}"
    )

    return {
        **state,
        "execution_result": result,
    }
