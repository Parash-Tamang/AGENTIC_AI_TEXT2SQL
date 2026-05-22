"""Routing functions — pure decision functions, no state mutation."""

from typing import Any, Dict


async def intent_router(state: Dict[str, Any]) -> str:
    """Route after intent_classifier.

    Reads state["intent"]["route_to"] which is set deterministically
    by IntentClassifier._derive_route() — never trusted from LLM.

    Returns:
        "QueryTranslation"    → query_decomposer (SQL path)
        "Generate"            → response_generator (narrative path)
        "ClarificationAgent"  → response_generator (low confidence)
    """
    intent_data = state.get("intent", {})
    return intent_data.get("route_to", "Generate")


async def sql_validation_router(state: Dict[str, Any]) -> str:
    MAX_RETRIES = 3
    passed = state.get("validation_passed")
    retry_count = state.get("retry_count", 0)
    validation = state.get("validation_result", {})
    needs_retry = validation.get("needs_retry", False)

    # only retry if validator explicitly asked for it AND under limit
    if passed is False and needs_retry and retry_count < MAX_RETRIES:
        state["retry_count"] = retry_count + 1
        return "sql_generator"

    # validation passed OR validator said retry=False → proceed to executor
    return "results_validator"


async def validation_router(state: Dict[str, Any]) -> str:
    """Route after sql_post_execution_validator.

    Priority:
      1. static validation failed  → retry sql_generator (up to 3x)
      2. self_rag_retry             → full pipeline retry from query_refiner
      3. otherwise                  → response_generator
    """
    MAX_RETRIES = 3
    passed = state.get("validation_passed")
    retry_count = state.get("retry_count", 0)

    # resolve self_rag_retry from dict or Pydantic model
    self_rag = state.get("self_rag_decision", {})
    self_rag_retry = (
        self_rag.get("self_rag_retry", False)
        if isinstance(self_rag, dict)
        else getattr(self_rag, "self_rag_retry", False)
    )

    if passed is False and retry_count < MAX_RETRIES:
        state["retry_count"] = retry_count + 1
        return "sql_generator"

    if self_rag_retry and retry_count < MAX_RETRIES:
        state["retry_count"] = retry_count + 1
        return "query_refiner"

    return "response"  # engine maps → response_generator


ROUTER_FNS = {
    "intent_router": intent_router,
    "sql_validation_router": sql_validation_router,
    "validation_router": validation_router,
}

__all__ = ["ROUTER_FNS"]
