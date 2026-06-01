from __future__ import annotations

import json
from typing import Any

from src.agent.observability import (
    configure_workflow_logging,
    finish_request_trace,
    log_event,
    start_request_trace,
    trace_node,
)
from src.agent.llm.registry import get_llm
from src.agent.nodes.query_refiner import query_refiner
from src.agent.nodes.intent_classifier import intent_classifier_node
from src.agent.nodes.decomposition import query_decomposer
from src.agent.nodes.views_agent import views_fetcher_node
from src.agent.nodes.schema_agent import schema_fetcher_node
from src.agent.nodes.sql_generator import sql_generator_node
from src.agent.nodes.rbac_enforcer import rbac_enforcer_node
from src.agent.nodes.sql_validator import sql_validator_node
from src.agent.tools.executor import executor_node
from src.agent.nodes.sql_results_validator import sql_post_execution_validator_node
from src.agent.nodes.generate_response import response_generator_node
from src.agent.nodes.visualization_agent import visualization_agent_node
from src.agent.orchestrator.engine import GraphEngine
from src.agent.memory.session_context import SessionContext, extract_from_state
from src.agent.nodes.state import create_initial_state


def _normalize_connection(connection: Any) -> dict[str, Any]:
    if connection is None:
        return {}
    if isinstance(connection, dict):
        return connection
    if hasattr(connection, "model_dump"):
        return connection.model_dump()
    if isinstance(connection, str):
        try:
            parsed = json.loads(connection)
        except json.JSONDecodeError as exc:
            raise TypeError(
                "connection must be a mapping or JSON object string"
            ) from exc
        if isinstance(parsed, dict):
            return parsed
    raise TypeError(f"Unsupported connection type: {type(connection).__name__}")


async def run_chat_pipeline(
    user_query: str,
    history: list[dict],
    connection: Any,
    user_role: str,
    model_name: str,
    domain_context: str = "general",
    prompt_client: Any = None,
    session_context: SessionContext | None = None,
) -> dict[str, Any]:
    """
    Builds and runs the full agent pipeline.
    Returns the final state dict.
    """
    configure_workflow_logging()
    from src.agent.tools.config import set_connection_config, ConnectionConfig

    connection_data = _normalize_connection(connection)

    llm = get_llm(model_name="sqlcoder")
    trace = start_request_trace(
        {
            "user_query": user_query,
            "model_name": model_name,
            "history_turns": len(history),
            "connection": {
                "db_type": connection_data.get("db_type", "mssql"),
                "server": connection_data.get("server"),
                "database": connection_data.get("database"),
            },
        }
    )
    log_event(
        stage="request",
        event="start",
        input_data={
            "user_query": user_query,
            "history": history,
            "connection": {
                "db_type": connection_data.get("db_type", "mssql"),
                "server": connection_data.get("server"),
                "database": connection_data.get("database"),
                "pool_size": connection_data.get("pool_size", 5),
                "timeout": connection_data.get("timeout", 30),
            },
            "model_name": model_name,
        },
        extra={"request_id": trace.request_id},
    )

    set_connection_config(
        ConnectionConfig(
            db_type=connection_data.get("db_type", "mssql"),
            server=connection_data["server"],
            database=connection_data["database"],
            username=connection_data["username"],
            password=connection_data["password"],
            port=connection_data.get("port"),
            pool_size=connection_data.get("pool_size", 5),
            timeout=connection_data.get("timeout", 30),
        )
    )

    initial_state = create_initial_state(
        user_query=user_query,
        user_role=user_role,
        domain_context=domain_context,
        history=history,
        connection=connection_data,
    )

    initial_state.update(
        {
            "retry_count": 0,
            "errors": [],
            "pool_size": connection_data.get("pool_size", 5),
            "timeout": connection_data.get("timeout", 30),
            "prompt_client": prompt_client,
        }
    )

    if session_context is not None:
        # Normalize SessionContext into the state's expected connection/session fields
        sc = session_context
        # Preferred names used elsewhere in the pipeline
        if getattr(sc, "session_id", None):
            initial_state["session_id"] = sc.session_id
        elif getattr(sc, "chat_id", None):
            initial_state["session_id"] = sc.chat_id

        if getattr(sc, "user_id", None):
            initial_state["user_id"] = sc.user_id

        # Map session-scoped db id to connection identifier used by nodes
        if getattr(sc, "db_id", None):
            initial_state["connection_id"] = sc.db_id

        if getattr(sc, "db_type", None):
            initial_state["db_type"] = sc.db_type

        # Preserve the full session context payload for downstream storage or auditing
        initial_state["session_context"] = sc.model_dump()

    llm = get_llm(model_name=model_name)
    # llm_sql = get_llm(
    #     model_name="sqlcoder"
    # )  # FIX: use SQL-specific model for SQL nodes
    nodes_registry = {
        "query_refiner": trace_node(
            "query_refiner",
            lambda s: query_refiner(llm, s),
            input_builder=lambda s: {
                "user_query": s.get("user_query"),
                "history": s.get("history"),
                "retry_feedback": s.get("retry_feedback"),
            },
            output_builder=lambda r: {
                "construct": r.get("construct"),
                "refined_query": r.get("refined_query"),
            },
        ),
        "intent_classifier": trace_node(
            "intent_classifier",
            lambda s: intent_classifier_node(llm, s),
            input_builder=lambda s: {
                "user_query": s.get("user_query"),
                "refined_query": s.get("refined_query"),
                "history": s.get("history"),
                "domain_context": s.get("domain_context"),
            },
            output_builder=lambda r: {
                "intent": r.get("intent"),
            },
        ),
        "query_decomposer": trace_node(
            "query_decomposer",
            lambda s: query_decomposer(llm, s),
            input_builder=lambda s: {
                "refined_query": s.get("refined_query"),
                "intent": s.get("intent"),
                "construct": s.get("construct"),
            },
            output_builder=lambda r: {
                "decomposed": r.get("decomposed"),
            },
        ),
        "views_fetcher": trace_node(
            "views_fetcher",
            lambda s: views_fetcher_node(llm, s),
            input_builder=lambda s: {
                "construct": s.get("construct"),
                "decomposed": s.get("decomposed"),  # FIX: needed for sub_queries
                "history": s.get("history"),
                "intent": s.get("intent"),
            },
            output_builder=lambda r: {
                "views": r.get("views"),
                "views_grade": r.get("views_grade"),
                "view_suggestions": r.get("view_suggestions"),  # FIX: was missing
            },
        ),
        "schema_fetcher": trace_node(
            "schema_fetcher",
            lambda s: schema_fetcher_node(llm, s),
            input_builder=lambda s: {
                "construct": s.get("construct"),
                "decomposed": s.get("decomposed"),
                "views_grade": s.get("views_grade"),
                "views": s.get("views"),
            },
            output_builder=lambda r: {
                "retrieved_schemas": r.get("retrieved_schemas"),
                "seed_tables": r.get("seed_tables"),
                "join_paths": r.get("join_paths"),
            },
        ),
        "sql_generator": trace_node(
            "sql_generator",
            lambda s: sql_generator_node(llm, s),
            input_builder=lambda s: {
                "construct": s.get("construct"),
                "retrieved_schemas": s.get("retrieved_schemas"),
                "seed_tables": s.get("seed_tables"),
                "join_paths": s.get("join_paths"),
                "views": s.get("views"),
                "retry_feedback": s.get("retry_feedback"),
            },
            output_builder=lambda r: {
                "generated_sql": r.get("generated_sql"),
                "token_count": r.get("token_count"),
                "hallucinated_tables": r.get("hallucinated_tables"),
            },
        ),
        "rbac_enforcer": trace_node(
            "rbac_enforcer",
            rbac_enforcer_node,
            input_builder=lambda s: {
                "generated_sql": s.get("generated_sql"),
                "allowed_tables": s.get("allowed_tables"),
                "mandatory_filters": s.get("mandatory_filters"),
            },
            output_builder=lambda r: {
                "generated_sql": r.get("generated_sql"),
                "permission_denied": r.get("permission_denied"),
                "user_facing_response": r.get("user_facing_response"),
                "validation_result": r.get("validation_result"),
                "rbac_enforced_filters": r.get("rbac_enforced_filters"),
            },
        ),
        "sql_validator": trace_node(
            "sql_validator",
            lambda s: sql_validator_node(llm, s),
            input_builder=lambda s: {
                "generated_sql": s.get("generated_sql"),
                "retrieved_schemas": s.get("retrieved_schemas"),
                "seed_tables": s.get("seed_tables"),
                "join_paths": s.get("join_paths"),
            },
            output_builder=lambda r: {
                "validation_passed": r.get("validation_passed"),
                "validation_result": r.get("validation_result"),
                "validation_errors": r.get("validation_errors"),
            },
        ),
        "executor": trace_node(
            "executor",
            executor_node,
            input_builder=lambda s: {
                "generated_sql": s.get("generated_sql"),
                "db_type": s.get("db_type"),
                "server": s.get("server"),
                "database": s.get("database"),
                "username": s.get("username"),
                "password": s.get("password"),
                "port": s.get("port"),
                "pool_size": s.get("pool_size"),
                "timeout": s.get("timeout"),
            },
            output_builder=lambda r: {
                "execution_result": (
                    r.get("execution_result") if isinstance(r, dict) else r
                ),
            },
        ),
        "sql_post_execution_validator": trace_node(
            "sql_post_execution_validator",
            lambda s: sql_post_execution_validator_node(llm, s),
            input_builder=lambda s: {
                "execution_result": s.get("execution_result"),
                "generated_sql": s.get("generated_sql"),
                "retrieved_schemas": s.get("retrieved_schemas"),
                "construct": s.get("construct"),
            },
            output_builder=lambda r: {
                "validation_passed": r.get("validation_passed"),
                "validation_error": r.get("validation_error"),
                "sql_errors": r.get("sql_errors"),
                "self_rag_decision": r.get("self_rag_decision"),
                "execution_analysis": r.get("execution_analysis"),
            },
        ),
        "visualization": trace_node(
            "visualization",
            lambda s: visualization_agent_node(s, viz_llm=llm),
            input_builder=lambda s: {
                "execution_result": s.get("execution_result"),
                "generated_sql": s.get("generated_sql"),
                "sanitised_schema": s.get("sanitised_schema"),
                "construct": s.get("construct"),
            },
            output_builder=lambda r: {
                "graph_data": r.get("graph_data"),
            },
        ),
        # FIX: response_generator now receives all keys it needs
        "response_generator": trace_node(
            "response_generator",
            lambda s: response_generator_node(llm, s),
            input_builder=lambda s: {
                "user_query": s.get("user_query"),
                "history": s.get("history"),  # FIX: was missing
                "intent": s.get("intent"),
                "construct": s.get("construct"),  # FIX: was missing
                "generated_sql": s.get("generated_sql"),
                "execution_result": s.get("execution_result"),
                "graph_data": s.get("graph_data"),
                "execution_analysis": s.get("execution_analysis"),
                "retrieved_schemas": s.get("retrieved_schemas"),  # FIX: was missing
                "view_suggestions": s.get("view_suggestions"),  # FIX: was missing
            },
            output_builder=lambda r: {
                "user_facing_response": r.get("user_facing_response"),
                "response_token_breakdown": r.get("response_token_breakdown"),
                "view_suggestions_shown": r.get(
                    "view_suggestions_shown"
                ),  # FIX: was missing
            },
        ),
    }

    engine = GraphEngine(nodes=nodes_registry)
    try:
        final_state = await engine.run(initial_state)

        # Enrich final_state with canonical session fields so downstream
        # `extract_from_state` can build a complete SessionContext payload.
        final_state["last_refined_query"] = final_state.get("refined_query")
        intent_obj = final_state.get("intent")
        if isinstance(intent_obj, dict):
            final_state["last_intent"] = intent_obj.get("intent")
        else:
            final_state["last_intent"] = None
        final_state["last_confirmed_sql"] = final_state.get("generated_sql")
        final_state["last_tables_used"] = final_state.get("seed_tables", [])
        final_state["last_filters"] = (
            final_state.get("last_filters") or final_state.get("filters") or {}
        )
        final_state["last_skeleton_id"] = final_state.get("last_skeleton_id")
        final_state["turn_count"] = (
            final_state.get("turn_number") or final_state.get("turn_count") or 1
        )

        # Remove runtime-only objects before tracing / returning state.
        final_state.pop("prompt_client", None)

        finish_request_trace(final_state=final_state, status="success")
        return final_state
    except Exception as exc:
        initial_state.pop("prompt_client", None)
        finish_request_trace(final_state=initial_state, error=str(exc), status="error")
        raise
