from __future__ import annotations

import json
from typing import List, Dict, Optional

from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM
from src.agent.prompt.refiner import REFINER_SYSTEM


class RefineResult(BaseModel):
    classification: str
    confidence: float = Field(ge=0.0, le=1.0)
    constructed_query: str
    reasoning: str

    def __str__(self) -> str:
        return (
            f"Classification  : {self.classification}\n"
            f"Confidence      : {self.confidence}\n"
            f"ConstructedQuery: {self.constructed_query}\n"
            f"Reasoning       : {self.reasoning}"
        )


# ---------------------------------------------------------------------------
# Core refiner
# ---------------------------------------------------------------------------


def query_refiner(
    llm: BaseLLM,
    user_query: str,
    system_prompt: str = REFINER_SYSTEM,
    history: Optional[List[Dict[str, str]]] = None,
) -> RefineResult:
    """
    Refine and classify a user query in a single LLM call.

    Args:
        llm:        Any BaseLLM implementation.
        user_query: The user's latest raw input.
        history:    Conversation history as list of {"role": ..., "content": ...}
                    passed directly into llm.generate(). None for first turn.

    Returns:
        RefineResult with classification, confidence, constructed_query, reasoning.
        Use constructed_query as the final query for your downstream pipeline.
    """
    raw = llm.generate(
        system_prompt=system_prompt, user_prompt=user_query, memeory=history or []
    )

    # Strip markdown fences if model wraps output in ```json ... ```
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        return RefineResult(
            classification=data.get("Classification", "FRESH"),
            confidence=float(data.get("Confidence", 0.0)),
            constructed_query=data.get("ConstructedQuery", user_query),
            reasoning=data.get("Reasoning", ""),
        )
    except (json.JSONDecodeError, ValueError):
        return RefineResult(
            classification="FRESH",
            confidence=0.0,
            constructed_query=user_query,
            reasoning="JSON parse failed — passing query through as-is.",
        )
