"""Workflow graph topology — node names, edges, and router keys."""

from __future__ import annotations

# ── Node → next mapping ───────────────────────────────────────────────
# Each node either has a fixed "next" or delegates to a "router" fn.

GRAPH: dict[str, dict] = {
    "query_refiner": {"next": "intent_classifier"},
    "intent_classifier": {"router": "intent_router"},
    "query_decomposer": {"next": "views_fetcher"},
    "views_fetcher": {"next": "schema_fetcher"},
    "schema_fetcher": {"next": "sql_generator"},
    "sql_generator": {"next": "sql_validator"},
    "sql_validator": {"router": "sql_validation_router"},
    "executor": {"next": "sql_post_execution_validator"},
    "sql_post_execution_validator": {"router": "validation_router"},
    "visualization": {"next": "response_generator"},
    "response_generator": {"next": None},
}

# ── Router outcome maps ───────────────────────────────────────────────
# Documents what string each router can return → which node it maps to.

ROUTERS: dict[str, dict[str, str | None]] = {
    "intent_router": {
        "QueryTranslation": "query_decomposer",  # SQL_QUERY intent
        "Generate": "response_generator",  # EXPLAIN/SUMMARIZE/GREETING
        "ClarificationAgent": "response_generator",  # confidence < 0.6
    },
    "sql_validation_router": {
        "sql_generator": "sql_generator",  # static check failed → retry
        "results_validator": "executor",  # static check passed → execute
    },
    "validation_router": {
        "sql_generator": "sql_generator",  # validation_passed False
        "query_refiner": "query_refiner",  # self_rag_retry → full retry
        "response": "response_generator",  # success
        "visualization": "visualization",  # route to visualization when requested
    },
}

START_NODE = "query_refiner"
END_NODES = frozenset({"response_generator"})

__all__ = ["GRAPH", "ROUTERS", "START_NODE", "END_NODES"]
