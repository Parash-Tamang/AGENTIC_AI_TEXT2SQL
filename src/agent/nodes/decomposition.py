from __future__ import annotations

import json
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM
from src.agent.utils.pretty_print import pretty_log
from src.agent.prompt.decomposition import DECOMPOSITION_SYSTEM
from src.agent.utils.prompt_utils import resolve_system_prompt

DOMAIN_CONTEXT_USAGE_INSTRUCTION = (
    "Use the provided domain context as the primary source for understanding the business domain, entities, relationships, terminology, and user intent. "
    "Refer to it when interpreting questions, resolving ambiguities, identifying relevant entities, and making business-aware decisions. "
    "Prioritize the domain context over assumptions and ensure all reasoning remains consistent with the described business processes and relationships."
)


class SubQuery(BaseModel):
    order: int
    query: str
    reasoning: str

    def __str__(self) -> str:
        return f"[{self.order}] {self.query} ({self.reasoning})"


class DecompositionResult(BaseModel):
    is_composite: bool
    sub_queries: List[SubQuery] = Field(default_factory=list)

    def __str__(self) -> str:
        if not self.is_composite:
            return "IsComposite     : False"

        sub_queries_str = "\n".join([str(sq) for sq in self.sub_queries])
        return f"IsComposite     : True\n" f"SubQueries      :\n{sub_queries_str}"


# ─────────────────────────────────────────────────────────────────────────────
# Query Decomposer
# ─────────────────────────────────────────────────────────────────────────────


def query_decomposer(
    llm: BaseLLM,
    state: dict[str, Any],
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """
    Decompose a constructed query into simpler sub-queries.

    Args:
        llm:           Any BaseLLM implementation.
        state:         LangGraph state dict containing:
                       - construct: dict (RefineResult.model_dump())
                         with "constructed_query" key
                       - domain_context: str (e.g. "school management system")
        system_prompt: Optional override for the system prompt.
                       If None, uses DECOMPOSITION_SYSTEM.

    Returns:
        dict with state["decomposed"] = DecompositionResult.model_dump()
    """
    construct = state.get("construct", {})
    constructed_query = construct.get("constructed_query", "")
    domain_context = state.get("domain_context", "general")

    # Priority: explicit param > API via state > local default
    if system_prompt:
        prompt = system_prompt
    else:
        prompt = resolve_system_prompt(state, "decomposition", DECOMPOSITION_SYSTEM)

    user_prompt = json.dumps(
        {
            "ConstructedQuery": constructed_query,
            "DomainContext": domain_context,
            "DomainContextUsageInstruction": DOMAIN_CONTEXT_USAGE_INSTRUCTION,
        },
        ensure_ascii=False,
    )

    # Request structured JSON output using DecompositionResult pydantic schema
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "decomposition_result",
            "schema": DecompositionResult.model_json_schema(),
        },
    }

    raw = llm.generate(
        system_prompt=prompt,
        user_prompt=user_prompt,
        response_format=response_format,
        json_mode=True,
    )

    try:
        if isinstance(raw, (dict, list)):
            data = raw
        else:
            cleaned = str(raw).strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()
            data = json.loads(cleaned)

        # Support both TitleCase keys (IsComposite/SubQueries) and snake_case
        is_composite = (
            data.get("is_composite")
            if data.get("is_composite") is not None
            else data.get("IsComposite", False)
        )
        sub_queries_data = (
            data.get("sub_queries")
            if data.get("sub_queries") is not None
            else data.get("SubQueries", [])
        )

        sub_queries = [
            SubQuery(
                order=sq.get("order", idx + 1),
                query=sq.get("query") or sq.get("question") or "",
                reasoning=sq.get("reasoning", ""),
            )
            for idx, sq in enumerate(sub_queries_data)
        ]

        result = DecompositionResult(
            is_composite=bool(is_composite), sub_queries=sub_queries
        )
    except Exception:
        result = DecompositionResult(is_composite=False, sub_queries=[])

    state["decomposed"] = result.model_dump()
    # Pretty print concise decomposition summary
    pretty_log(
        "Decomposer",
        state={"constructed_query": constructed_query},
        llm_metrics={"token_breakdown": {}, "latency_ms": None},
        extra={
            "is_composite": result.is_composite,
            "sub_queries": [s.order for s in result.sub_queries],
        },
    )

    return state


# from src.agent.llm.registry import get_llm

# llm = get_llm("openai/gpt-oss-20b")
# state = {
#     "construct": {
#         "constructed_query": "students who comes always late and teachers too."
#     },
#     "domain_context": "retail / CRM",
# }
# result = query_decomposer(llm=llm, state=state)
# decomposed = result["decomposed"]
# print(result)
