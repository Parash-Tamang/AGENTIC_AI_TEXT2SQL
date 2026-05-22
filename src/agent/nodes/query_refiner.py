"""
Query Refiner  (Pydantic v2)
============================

Classifies and refines user queries before they enter the SQL pipeline.

Classifications
---------------
FRESH    - Brand-new independent query; no prior context needed.
CONTINUE - Follow-up query; merged with conversation history.
RETRY    - Previous SQL attempt failed; query reconstructed from validator feedback.

The RETRY path is triggered automatically when ``state["retry_feedback"]`` is
populated by the post-execution validator (sql_post_execution_validator_node).

Usage
-----
    from query_refiner import query_refiner, RefineResult

    # Normal call (FRESH / CONTINUE)
    state = query_refiner(llm=my_llm, state={
        "user_query": "total sales per region",
        "history": [...],
    })

    # Retry call (RETRY) — retry_feedback injected by validator orchestrator
    state = query_refiner(llm=my_llm, state={
        "user_query": "total sales per region",
        "history": [...],
        "retry_feedback": {
            "issues":      ["empty_result"],
            "reasoning":   "WHERE clause filtered all rows.",
            "failed_sql":  "SELECT region, SUM(amount) FROM sales_summary ...",
            "hint":        "Use sales_fact table instead",
            "attempt":     1,
        },
    })

    print(state["construct"])
    # {
    #   "classification":  "RETRY",
    #   "confidence":       0.97,
    #   "constructed_query":"Get total sales grouped by region from sales_fact ...",
    #   "reasoning":       "Reconstructed after empty_result on attempt 1.",
    # }
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from src.agent.llm.base import BaseLLM
from src.agent.prompt.refiner import REFINER_SYSTEM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_CLASSIFICATIONS = frozenset({"FRESH", "CONTINUE", "RETRY"})

# Maps issue keys from the validator to plain-English hints injected into the
# LLM prompt when no explicit hint was provided by the validator.
_ISSUE_HINTS: Dict[str, str] = {
    "empty_result": "Broaden filter conditions or check if the correct table is referenced.",
    "join_explosion": "Specify explicit JOIN keys to avoid a cartesian product.",
    "duplicate_rows": "Add GROUP BY or DISTINCT to remove duplicate rows.",
    "missing_tables": "Reference the correct table name as per the schema.",
    "missing_columns": "Reference the correct column name as per the schema.",
    "syntax_error": "Simplify and clarify the SQL structure.",
    "aggregation_issues": "Be explicit about the aggregation function and grouping columns.",
    "semantic_invalid": "Restate the query with more precise business terminology.",
    "execution_error": "Avoid complex expressions; simplify the query.",
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class RetryFeedback(BaseModel):
    """Structured feedback from the post-execution SQL validator."""

    issues: List[str] = Field(default_factory=list)
    reasoning: str = Field(default="")
    failed_sql: str = Field(default="")
    hint: str = Field(default="")
    attempt: int = Field(default=1)

    @field_validator("issues", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [v]
        return v or []


class RefineResult(BaseModel):
    """Output of the query refiner node."""

    classification: str = Field(description="FRESH | CONTINUE | RETRY")
    confidence: float = Field(ge=0.0, le=1.0)
    constructed_query: str = Field(description="Refined, self-contained query")
    reasoning: str = Field(default="")

    @field_validator("classification", mode="before")
    @classmethod
    def normalise_classification(cls, v: Any) -> str:
        val = str(v).upper().strip()
        return val if val in _VALID_CLASSIFICATIONS else "FRESH"

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp(cls, v: Any) -> float:
        return max(0.0, min(1.0, float(v or 0.0)))

    def __str__(self) -> str:
        return (
            f"Classification  : {self.classification}\n"
            f"Confidence      : {self.confidence}\n"
            f"ConstructedQuery: {self.constructed_query}\n"
            f"Reasoning       : {self.reasoning}"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_retry_feedback(raw: Any) -> Optional[RetryFeedback]:
    """
    Coerce ``state["retry_feedback"]`` into a ``RetryFeedback`` instance.

    Accepts:
    - ``RetryFeedback`` instance (pass-through)
    - ``dict``  (validated via Pydantic)
    - ``None``  (returns None)
    """
    if raw is None:
        return None
    if isinstance(raw, RetryFeedback):
        return raw
    if isinstance(raw, dict):
        try:
            return RetryFeedback(**raw)
        except Exception as exc:
            logger.warning("retry_feedback parse error — ignoring: %s", exc)
            return None
    logger.warning("retry_feedback has unexpected type %s — ignoring.", type(raw))
    return None


def _build_retry_hint(feedback: RetryFeedback) -> str:
    """
    Derive a human-readable hint string from validator issues.

    Uses the explicit ``feedback.hint`` when available; falls back to the
    built-in ``_ISSUE_HINTS`` map for each issue key.
    """
    if feedback.hint:
        return feedback.hint

    hints: List[str] = []
    for issue in feedback.issues:
        # issue keys may be "semantic_critical:some_detail" — strip suffix
        base_key = issue.split(":", 1)[0]
        if base_key in _ISSUE_HINTS:
            hints.append(_ISSUE_HINTS[base_key])

    return (
        " ".join(hints) if hints else "Rewrite the query to avoid the reported issues."
    )


def _build_user_prompt(
    user_query: str,
    feedback: Optional[RetryFeedback],
) -> str:
    """
    Build the user-facing prompt sent to the LLM.

    For RETRY, a structured ``RetryContext`` block is appended so the model
    knows exactly what went wrong and how to fix it.
    """
    if feedback is None:
        return user_query

    hint = _build_retry_hint(feedback)

    retry_block = {
        "OriginalQuery": user_query,
        "RetryContext": {
            "issues": feedback.issues,
            "reasoning": feedback.reasoning,
            "failed_sql": feedback.failed_sql,
            "hint": hint,
            "attempt": feedback.attempt,
        },
    }

    return json.dumps(retry_block, ensure_ascii=False)


def _strip_markdown_fences(raw: str) -> str:
    """Remove ```json … ``` wrappers that some models add around JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    return cleaned


def _parse_llm_response(raw: str, fallback_query: str) -> RefineResult:
    """
    Parse LLM JSON output into a ``RefineResult``.

    Falls back gracefully on parse failure — never raises.
    """
    try:
        data = json.loads(_strip_markdown_fences(raw))
        return RefineResult(
            classification=data.get("Classification", "FRESH"),
            confidence=float(data.get("Confidence", 0.0)),
            constructed_query=data.get("ConstructedQuery") or fallback_query,
            reasoning=data.get("Reasoning", ""),
        )
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "query_refiner: LLM JSON parse failed (%s) — using fallback.", exc
        )
        return RefineResult(
            classification="FRESH",
            confidence=0.0,
            constructed_query=fallback_query,
            reasoning="JSON parse failed — passing query through as-is.",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def query_refiner(
    llm: BaseLLM,
    state: Dict[str, Any],
    system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Refine and classify a user query in a single LLM call.

    Reads from state
    ----------------
    user_query     : str                    - Raw user input (required).
    history        : List[Dict[str, str]]   - Conversation history (optional).
    retry_feedback : dict | RetryFeedback   - Validator feedback (optional).
                     When present the classification is forced to RETRY and
                     the query is reconstructed to avoid known SQL failures.

    Writes to state
    ---------------
    construct      : dict          - Full ``RefineResult`` as a plain dict.
    refined_query  : str           - The ``constructed_query`` field (shortcut).
    retry_feedback : None          - Cleared after consumption to prevent
                                     re-triggering on subsequent calls.

    Args:
        llm:           Any ``BaseLLM`` implementation.
        state:         LangGraph / plain state dict (mutated in-place).
        system_prompt: Optional system prompt override.
                       Defaults to ``REFINER_SYSTEM``.

    Returns:
        The same ``state`` dict with ``construct`` and ``refined_query`` set.
    """
    user_query: str = state.get("user_query", "")
    history: List[Dict[str, Any]] = state.get("history", [])
    raw_feedback: Any = state.get("retry_feedback")

    feedback: Optional[RetryFeedback] = _parse_retry_feedback(raw_feedback)

    # Build prompt
    prompt: str = system_prompt or REFINER_SYSTEM
    user_prompt: str = _build_user_prompt(user_query, feedback)

    logger.debug(
        "query_refiner called | has_feedback=%s | query=%r",
        feedback is not None,
        user_query[:80],
    )

    # LLM call
    try:
        raw_output: str = llm.generate(
            system_prompt=prompt,
            user_prompt=user_prompt,
            memory=history,
        )
        print(raw_output)
    except Exception as exc:
        logger.error("query_refiner: LLM call failed: %s", exc)
        # Safe fallback — treat as FRESH pass-through
        result = RefineResult(
            classification="FRESH",
            confidence=0.0,
            constructed_query=user_query,
            reasoning=f"LLM call failed: {exc}",
        )
        state["construct"] = result.model_dump()
        state["refined_query"] = result.constructed_query
        return state

    # Parse response
    result: RefineResult = _parse_llm_response(raw_output, fallback_query=user_query)

    # If retry_feedback was present but LLM somehow returned FRESH/CONTINUE,
    # override classification to RETRY to ensure downstream consistency.
    if feedback is not None and result.classification != "RETRY":
        logger.warning(
            "query_refiner: retry_feedback present but LLM returned %s — overriding to RETRY.",
            result.classification,
        )
        result = result.model_copy(update={"classification": "RETRY"})

    logger.info(
        "query_refiner | classification=%s confidence=%.2f query=%r",
        result.classification,
        result.confidence,
        result.constructed_query[:80],
    )

    # Write outputs
    state["construct"] = result.model_dump()
    state["refined_query"] = result.constructed_query

    # Clear retry_feedback after consumption so it does not bleed into the
    # next fresh request on the same state object.
    if feedback is not None:
        state["retry_feedback"] = None

    return state
