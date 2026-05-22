"""
Shared RAG State for LangGraph workflow.

This state definition is used across all sub-agents:
  - QueryRefiner (produces construct)
  - QueryDecomposer (produces decomposed)
  - IntentClassifier (produces intent)
"""

from __future__ import annotations

import json
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Input/Intermediate Models
# ─────────────────────────────────────────────────────────────────────────────


class ConstructData(BaseModel):
    """Output from QueryRefiner node."""

    classification: str
    confidence: float = Field(ge=0.0, le=1.0)
    constructed_query: str
    reasoning: str


class SubQueryData(BaseModel):
    """Individual sub-query in decomposition."""

    order: int
    query: str
    reasoning: str


class DecomposedData(BaseModel):
    """Output from QueryDecomposer node."""

    is_composite: bool
    sub_queries: List[SubQueryData] = Field(default_factory=list)


class IntentData(BaseModel):
    """Output from IntentClassifier node."""

    intent: str
    route_to: str
    confidence: float
    output_format: Optional[str] = None
    graph_type: Optional[str] = None
    reasoning: str


class RetryFeedback(BaseModel):
    """Structured feedback for query refiner retry flows."""

    issues: List[str] = Field(default_factory=list)
    reasoning: str = ""
    failed_sql: str = ""
    hint: str = ""
    attempt: int = 1


class ViewInfo(BaseModel):
    """Individual view with source query tracking."""

    name: Optional[str] = None
    view_name: Optional[str] = None
    description: Optional[str] = None
    schema: Optional[str] = None
    source_queries: List[str] = Field(default_factory=list)


class ViewsData(BaseModel):
    """Output from ViewsFetcher node."""

    views: List[ViewInfo] = Field(default_factory=list)
    unique_count: int = 0
    query_map: Dict[str, List[str]] = Field(default_factory=dict)
    errors: List[Dict[str, str]] = Field(default_factory=list)


class SchemaInfo(BaseModel):
    """Individual schema with source query tracking."""

    name: Optional[str] = None
    schema_name: Optional[str] = None
    description: Optional[str] = None
    tables: Optional[List[str]] = None
    source_queries: List[str] = Field(default_factory=list)


class SchemasData(BaseModel):
    """Output from SchemaFetcher node."""

    schemas: List[SchemaInfo] = Field(default_factory=list)
    unique_count: int = 0
    query_map: Dict[str, List[str]] = Field(default_factory=dict)
    errors: List[Dict[str, str]] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Main RAG State
# ─────────────────────────────────────────────────────────────────────────────


class RAGState(BaseModel):
    """
    Shared LangGraph state for Text-to-SQL RAG pipeline.

    Flow:
      1. QueryRefiner: user_query → construct
      2. QueryDecomposer: construct + domain_context → decomposed
      3. IntentClassifier: construct + domain_context → intent
      4. Router: intent.route_to → next node (QueryTranslation or Generate)
    """

    # ── INPUT FIELDS ──────────────────────────────────────────────────────────
    # User-provided inputs
    user_query: str
    domain_context: str = "general"
    history: List[Dict[str, str]] = Field(default_factory=list)

    # ── CONNECTION FIELDS ─────────────────────────────────────────────────────
    db_type: Optional[str] = None
    server: Optional[str] = None
    database: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    port: Optional[int] = None

    # ── INTERMEDIATE FIELDS ───────────────────────────────────────────────────
    # Produced by sub-agents
    construct: Optional[ConstructData] = None
    decomposed: Optional[DecomposedData] = None
    intent: Optional[IntentData] = None
    views: Optional[ViewsData] = None
    views_grade: Optional[Dict[str, Any]] = None
    schemas: Optional[SchemasData] = None
    retry_feedback: Optional[RetryFeedback] = None
    view_suggestions: List[Dict[str, Any]] = Field(default_factory=list)
    # Backwards-compatible aliases / workflow artifacts used by nodes
    # `retrieved_schemas` is written by `schema_fetcher_node` (list of schema dicts)
    retrieved_schemas: List[Dict[str, Any]] = Field(default_factory=list)
    # List of seed table names (unqualified) discovered by schema agent
    seed_tables: List[str] = Field(default_factory=list)
    # Discovered join paths from BFS (can be dict paths or relation strings)
    join_paths: List[Any] = Field(default_factory=list)
    # Post-BFS schema coverage checks from schema agent
    schema_coverage: Optional[Dict[str, Any]] = None
    schema_coverage_history: List[Dict[str, Any]] = Field(default_factory=list)
    # Convenience: some nodes expect a top-level refined_query string
    refined_query: Optional[str] = None

    # ── METADATA FIELDS ───────────────────────────────────────────────────────
    # For tracking and debugging
    session_id: Optional[str] = None
    turn_number: int = 0
    errors: List[str] = Field(default_factory=list)
    # ── Generator / Validator Outputs (placeholders used across nodes)
    generated_sql: Optional[str] = None
    token_count: int = 0
    token_breakdown: Dict[str, Any] = Field(default_factory=dict)
    sql_errors: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    hallucinated_tables: List[str] = Field(default_factory=list)
    validation_result: Optional[Dict[str, Any]] = None
    validation_passed: Optional[bool] = None
    suggested_fix: str = ""
    # Post-execution validation fields (populated by results validator)
    execution_result: Optional[Dict[str, Any]] = None
    execution_analysis: Optional[Dict[str, Any]] = None
    validation_with_llm: Optional[Dict[str, Any]] = None
    self_rag_decision: Optional[Dict[str, Any]] = None
    validation_token_breakdown: Dict[str, Any] = Field(default_factory=dict)
    validation_error: Optional[str] = None
    execution_issues: List[str] = Field(default_factory=list)
    # Optional structural validation baked into state
    validation_structural: Optional[Dict[str, Any]] = None
    # Response node outputs
    user_facing_response: Optional[str] = None
    response_token_breakdown: Dict[str, Any] = Field(default_factory=dict)
    response_error: Optional[str] = None

    class Config:
        """Allow arbitrary types for LangGraph compatibility."""

        arbitrary_types_allowed = True


# ─────────────────────────────────────────────────────────────────────────────
# State Initialization Helper
# ─────────────────────────────────────────────────────────────────────────────


def _normalize_connection(connection: Optional[Any]) -> dict[str, Any]:
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
            raise TypeError("connection must be a mapping or JSON object string") from exc
        if isinstance(parsed, dict):
            return parsed
    raise TypeError(f"Unsupported connection type: {type(connection).__name__}")


def create_initial_state(
    user_query: str,
    domain_context: str = "general",
    history: Optional[List[Dict[str, str]]] = None,
    session_id: Optional[str] = None,
    connection: Optional[Dict[str, Any]] = None,
) -> dict[str, Any]:
    connection_data = _normalize_connection(connection)
    state = RAGState(
        user_query=user_query,
        domain_context=domain_context,
        history=history or [],
        session_id=session_id,
        turn_number=1,
        refined_query=user_query,
        db_type=connection_data.get("db_type"),
        server=connection_data.get("server"),
        database=connection_data.get("database"),
        username=connection_data.get("username"),
        password=connection_data.get("password"),
        port=connection_data.get("port"),
    )
    return state.model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# State Access Helpers
# ─────────────────────────────────────────────────────────────────────────────


def get_refined_query(state: dict[str, Any]) -> str:
    """Extract refined query from state."""
    construct = state.get("construct", {})
    return construct.get("constructed_query", state.get("user_query", ""))


def is_decomposed_composite(state: dict[str, Any]) -> bool:
    """Check if query was decomposed into multiple sub-queries."""
    decomposed = state.get("decomposed", {})
    return decomposed.get("is_composite", False)


def get_next_route(state: dict[str, Any]) -> str:
    """Get the next node to route to based on intent."""
    intent = state.get("intent", {})
    return intent.get("route_to", "Generate")


def get_retry_feedback(state: dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract retry feedback from state."""
    retry_feedback = state.get("retry_feedback")
    if isinstance(retry_feedback, dict):
        return retry_feedback
    return None


def add_error(state: dict[str, Any], error_msg: str) -> dict[str, Any]:
    """Add an error message to state."""
    if "errors" not in state:
        state["errors"] = []
    state["errors"].append(error_msg)
    return state


def get_fetched_views(state: dict[str, Any]) -> List[Dict]:
    """Extract fetched views and their source queries."""
    views_data = state.get("views", {})
    if isinstance(views_data, dict):
        return views_data.get("views", [])
    return []


def get_view_sources(state: dict[str, Any]) -> Dict[str, List[str]]:
    """Get mapping of query → [view_names] for later analysis."""
    views_data = state.get("views", {})
    if isinstance(views_data, dict):
        return views_data.get("query_map", {})
    return {}


def get_fetched_schemas(state: dict[str, Any]) -> List[Dict]:
    """Extract fetched schemas and their source queries."""
    schemas_data = state.get("schemas", {})
    if isinstance(schemas_data, dict):
        return schemas_data.get("schemas", [])
    return []


def get_schema_sources(state: dict[str, Any]) -> Dict[str, List[str]]:
    """Get mapping of query → [schema_names] for later analysis."""
    schemas_data = state.get("schemas", {})
    if isinstance(schemas_data, dict):
        return schemas_data.get("query_map", {})
    return {}


def get_views_grade(state: dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract views grading result from state."""
    views_grade = state.get("views_grade")
    if isinstance(views_grade, dict):
        return views_grade
    return None


def is_views_sufficient(state: dict[str, Any]) -> bool:
    """Check if views are graded as sufficient."""
    views_grade = state.get("views_grade", {})
    if isinstance(views_grade, dict):
        return views_grade.get("answer", "no").lower() == "yes"
    return False


def get_schema_coverage(state: dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract latest schema coverage validation from state."""
    coverage = state.get("schema_coverage")
    if isinstance(coverage, dict):
        return coverage
    return None


def get_schema_coverage_history(state: dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract schema coverage retry history from state."""
    history = state.get("schema_coverage_history", [])
    return history if isinstance(history, list) else []


def get_execution_result(state: dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract raw execution result from state."""
    execution_result = state.get("execution_result")
    if isinstance(execution_result, dict):
        return execution_result
    return None


def get_validation_errors(state: dict[str, Any]) -> List[str]:
    """Extract validation error list from state."""
    errors = state.get("validation_errors", [])
    return errors if isinstance(errors, list) else []


def get_suggested_fix(state: dict[str, Any]) -> str:
    """Extract suggested SQL fix from state."""
    fix = state.get("suggested_fix", "")
    return fix if isinstance(fix, str) else ""


def get_view_suggestions(state: dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract view suggestion chips from state."""
    suggestions = state.get("view_suggestions", [])
    return suggestions if isinstance(suggestions, list) else []


def get_self_rag_decision(state: dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract Self-RAG decision from state."""
    decision = state.get("self_rag_decision")
    if isinstance(decision, dict):
        return decision
    return None
