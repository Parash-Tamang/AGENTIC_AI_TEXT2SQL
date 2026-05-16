"""
Tool executor — abstracts connection details from the LLM.
Imports only from config.py and external packages — never from this package root.
"""

import json
from typing import Any

from src.agent.tools.config import get_connection_config
from src.database.executor import (
    execute_query as _execute_query,
    execute_view as _execute_view,
)


def _handle_execute_query(inputs: dict) -> dict:
    conn = get_connection_config()
    print(f"   🔍 SQL: {inputs['sql'][:120]}...")
    return _execute_query(
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
    )


def _handle_execute_view(inputs: dict) -> dict:
    conn = get_connection_config()
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


def _handle_fetch_schema(inputs: dict) -> list:
    from src.knowledgebase.stores.vector_store import VectorStore
    from src.knowledgebase.stores.embedder import Embedder

    conn = get_connection_config()
    vector_store = VectorStore()
    embedder = Embedder()

    print(f"   📥 fetch_schema query='{inputs['query']}' db='{conn.database}'")
    embedding = embedder.embed(inputs["query"])
    results = vector_store.query_schemas(
        embedding=embedding,
        database_name=conn.database,
        top_k=inputs.get("top_k", 5),
        schema_name=inputs.get("schema_name"),
        table_name=inputs.get("table_name"),
    )
    print(f"   📤 fetch_schema returned {len(results)} results")
    return results


def _handle_fetch_view(inputs: dict) -> list:
    from src.knowledgebase.stores.vector_store import VectorStore
    from src.knowledgebase.stores.embedder import Embedder

    conn = get_connection_config()
    vector_store = VectorStore()
    embedder = Embedder()

    print(f"   📥 fetch_view query='{inputs['query']}' db='{conn.database}'")
    embedding = embedder.embed(inputs["query"])
    results = vector_store.query_views(
        embedding=embedding,
        database_name=conn.database,
        top_k=inputs.get("top_k", 5),
        schema_name=inputs.get("schema_name"),
        view_name=inputs.get("view_name"),
    )
    print(f"   📤 fetch_view returned {len(results)} results")
    return results


def _handle_bfs_join(inputs: dict) -> dict:
    from src.knowledgebase.graph.search_graph import bfs_schema_with_joins as _bfs
    from src.knowledgebase.graph.build_ import build_schema_graph

    conn = get_connection_config()
    print(f"   📥 bfs_join seeds={inputs['seed_tables']}")
    graph = build_schema_graph(
        db_type=conn.db_type,
        server=conn.server,
        database=conn.database,
        username=conn.username,
        password=conn.password,
        port=conn.port,
    )
    result = _bfs(
        graph=graph,
        seed_tables=inputs["seed_tables"],
        max_hops=inputs.get("max_hops", 2),
        token_limit=inputs.get("token_limit", 8000),
    )
    print(f"   📤 bfs_join discovered {len(result.get('tables', []))} tables")
    return result


_HANDLERS: dict[str, Any] = {
    "execute_query": _handle_execute_query,
    "execute_view": _handle_execute_view,
    "fetch_schema": _handle_fetch_schema,
    "fetch_view": _handle_fetch_view,
    "bfs_join": _handle_bfs_join,
}


def dispatch(tool_name: str, tool_inputs: str | dict) -> str:
    handler = _HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(
            f"Unknown tool '{tool_name}'. Available: {list(_HANDLERS.keys())}"
        )
    if isinstance(tool_inputs, str):
        tool_inputs = json.loads(tool_inputs)

    # Strip nulls — model sends null for optional fields it doesn't need
    tool_inputs = {k: v for k, v in tool_inputs.items() if v is not None}

    result = handler(tool_inputs)
    return json.dumps(result, default=str)


def dispatch_to_tool_result(tool_use_block) -> dict:
    """Anthropic-style tool_result block wrapper."""
    try:
        content = dispatch(tool_use_block.name, tool_use_block.input)
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
