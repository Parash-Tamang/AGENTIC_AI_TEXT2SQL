"""LangGraph graph assembly.

Wires all nodes and conditional edges into a compiled StateGraph.
Import build_graph() and call it once at startup.
"""

from __future__ import annotations

from langgraph.graph import StateGraph, END
from src.agent.nodes.state import RAGState
from src.agent.llm.registry import get_llm

# nodes
from src.agent.nodes.query_refiner import query_refiner_node
from src.agent.nodes.intent_classifier import intent_classifier_node
from src.agent.nodes.decomposition import query_decomposer_node
from src.agent.nodes.views_agent import views_fetcher_node
from src.agent.nodes.schema_agent import schema_fetcher_node
from src.agent.nodes.sql_generator import sql_generator_node
from src.agent.nodes.sql_validator import sql_validator_node
from src.agent.tools.executor import executor_node
from src.agent.nodes.sql_results_validator import (
    sql_post_execution_validator_node,
)
from src.agent.nodes.generate_response import response_generator_node

# routers
from src.agent.orchestrator.router import (
    intent_router,
    sql_validation_router,
    validation_router,
)


def build_graph(llm) -> StateGraph:
    """Compile and return the LangGraph StateGraph."""

    sg = StateGraph(RAGState)
    sql_llm = get_llm(model_name="sqlcoder")

    # ── register nodes ────────────────────────────────────────────────────
    sg.add_node("query_refiner", lambda s: query_refiner_node(llm, s))
    sg.add_node("intent_classifier", lambda s: intent_classifier_node(llm, s))
    sg.add_node("query_decomposer", lambda s: query_decomposer_node(llm, s))
    sg.add_node("views_fetcher", views_fetcher_node)
    sg.add_node("schema_fetcher", schema_fetcher_node)
    sg.add_node("sql_generator", lambda s: sql_generator_node(sql_llm, s))
    sg.add_node("sql_validator", sql_validator_node)
    sg.add_node("executor", executor_node)
    sg.add_node(
        "sql_post_execution_validator",
        lambda s: sql_post_execution_validator_node(llm, s),
    )
    sg.add_node("response_generator", lambda s: response_generator_node(llm, s))

    # ── fixed edges ───────────────────────────────────────────────────────
    sg.set_entry_point("query_refiner")
    sg.add_edge("query_refiner", "intent_classifier")
    sg.add_edge("query_decomposer", "views_fetcher")
    sg.add_edge("views_fetcher", "schema_fetcher")
    sg.add_edge("schema_fetcher", "sql_generator")
    sg.add_edge("sql_generator", "sql_validator")
    sg.add_edge("executor", "sql_post_execution_validator")
    sg.add_edge("response_generator", END)

    # ── conditional edges (routers) ───────────────────────────────────────
    sg.add_conditional_edges(
        "intent_classifier",
        intent_router,
        {
            "QueryTranslation": "query_decomposer",
            "Generate": "response_generator",
            "ClarificationAgent": "response_generator",
        },
    )
    sg.add_conditional_edges(
        "sql_validator",
        sql_validation_router,
        {
            "sql_generator": "sql_generator",
            "results_validator": "executor",
        },
    )
    sg.add_conditional_edges(
        "sql_post_execution_validator",
        validation_router,
        {
            "sql_generator": "sql_generator",
            "query_refiner": "query_refiner",
            "response": "response_generator",
        },
    )

    return sg.compile()
