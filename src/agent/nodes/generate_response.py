from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.agent.llm.base import BaseLLM
from pydantic import BaseModel, Field, field_validator, model_validator
from src.agent.utils.pretty_print import pretty_log
from src.agent.utils.token_counter import count_tokens

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent / "logs"
RESPONSE_LOG = LOG_DIR / "response_generator.jsonl"

# token counting is provided by src.agent.utils.token_counter.count_tokens


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_RESULT_ROWS_IN_PROMPT = 20
_MAX_HISTORY_TURNS = 10


def _normalize_state(state: Any) -> Dict[str, Any]:
    if isinstance(state, dict):
        return state
    if hasattr(state, "model_dump"):
        dumped = state.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if isinstance(state, str):
        try:
            parsed = json.loads(state)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


# ---------------------------------------------------------------------------
# System Prompt — strict no-leak policy baked in
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "You are a helpful, friendly data assistant. Your job is to explain query results "
    "to the user in plain, natural language — like a knowledgeable colleague, not a database engineer.\n\n"
    "=== STRICT RULES — NEVER VIOLATE ===\n"
    "1. NEVER mention table names, column names, SQL, schemas, joins, or any technical system detail.\n"
    "2. NEVER reveal how the data was retrieved, what query was run, or how the system works internally.\n"
    "3. NEVER expose error messages, stack traces, pipeline metadata, or execution details.\n"
    "4. If the user asks how you got the data or what query you used, respond naturally: "
    "e.g. 'I looked that up for you' — do not disclose any technical detail whatsoever.\n"
    "5. If results are empty, say something like 'I couldn't find any matching data for your request' "
    "— never say 'the table returned 0 rows' or use any technical language.\n"
    "6. If results are partial or limited, say 'here are the top results I found' — "
    "do not mention row limits, query limits, or execution details.\n"
    "7. The payload you receive contains internal fields (schemas, queries, flags) "
    "— treat ALL of it as strictly confidential. Only the user_raw_query and results_summary "
    "are relevant to your response.\n\n"
    "=== YOUR TONE ===\n"
    "- Warm, clear, and concise.\n"
    "- Summarise the data in 2-4 sentences, then present it in a clean readable format.\n"
    "- Use bullet points or a simple table if there are multiple rows.\n"
    "- Always end with a natural follow-up offer, e.g. 'Would you like to dig deeper into any of these?'\n"
    "- Match the tone of the conversation history if available.\n\n"
    "Respond ONLY with the user-facing message. No JSON, no preamble, no system commentary.\n"
)


# ===========================================================================
# Internal helper models (not exposed in RAGState)
# ===========================================================================


class _SchemaSummary(BaseModel):
    """Lightweight table->columns map built from raw schemas."""

    tables: Dict[str, List[str]] = Field(default_factory=dict)

    @classmethod
    def from_raw_schemas(cls, raw_schemas: List[Any]) -> "_SchemaSummary":
        tables: Dict[str, List[str]] = {}

        for schema in raw_schemas:
            if hasattr(schema, "model_dump"):
                schema = schema.model_dump()
            elif not isinstance(schema, dict):
                table_name = (
                    getattr(schema, "table_name", None)
                    or getattr(schema, "view_name", None)
                    or getattr(schema, "name", None)
                )
                columns_raw = getattr(schema, "columns", None) or []
                if table_name and columns_raw:
                    cols: List[str] = []
                    for c in columns_raw:
                        if hasattr(c, "model_dump"):
                            c = c.model_dump()
                        if isinstance(c, dict):
                            cols.append(
                                str(c.get("name") or c.get("column_name") or "")
                            )
                        elif isinstance(c, str):
                            cols.append(c)
                        else:
                            cols.append(str(getattr(c, "name", "")))
                    tables[str(table_name)] = [c for c in cols if c]
                    continue
                continue

            table_name = (
                schema.get("table_name")
                or schema.get("table")
                or schema.get("name")
                or schema.get("view_name")
            )
            columns_raw = schema.get("columns") or schema.get("fields") or []

            if table_name and columns_raw:
                cols = []
                for c in columns_raw:
                    if isinstance(c, dict):
                        cols.append(str(c.get("name") or c.get("column_name") or ""))
                    elif hasattr(c, "model_dump"):
                        c_dump = c.model_dump()
                        cols.append(
                            str(c_dump.get("name") or c_dump.get("column_name") or "")
                        )
                    elif isinstance(c, str):
                        cols.append(c)
                    else:
                        cols.append(str(getattr(c, "name", "")))
                tables[str(table_name)] = [c for c in cols if c]
                continue

            for k, v in schema.items():
                if isinstance(v, list) and k not in ("errors", "views", "schemas"):
                    tables[k] = [str(i) for i in v]

        return cls(tables=tables)


class ResponseNodeOutput(BaseModel):
    """Structured output written back into RAGState."""

    response: str = Field(description="User-facing natural language response")
    token_breakdown: Dict[str, int] = Field(default_factory=dict)
    is_empty_result: bool = Field(default=False)
    is_error: bool = Field(default=False)


# ===========================================================================
# View suggestion helpers
# ===========================================================================


def _extract_view_suggestions(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pull view_suggestions from state (written by views_fetcher_node).
    Returns a list of suggestion dicts, empty list if none.
    Each dict has: view_name, display_label, description, suggestion_reason, relevance_score.
    """
    raw = state.get("view_suggestions") or []
    if not isinstance(raw, list):
        return []
    suggestions = []
    for s in raw:
        if isinstance(s, dict) and s.get("view_name") and s.get("display_label"):
            suggestions.append(s)
        elif hasattr(s, "model_dump"):
            d = s.model_dump()
            if d.get("view_name") and d.get("display_label"):
                suggestions.append(d)
    return suggestions


def _should_show_suggestions(
    suggestions: List[Dict[str, Any]],
    results_status: str,
) -> bool:
    """
    Decide whether to append suggestion chips to the response.

    Show suggestions when:
      - There are any suggestions at all, AND one of:
        a) Results are empty (no direct answer found — related views help most here)
        b) Results are partial/ok but related_alternative suggestions exist
           (user might want a pre-built view for a richer answer)

    Never show suggestions if results are an error (confusing UX).
    """
    if not suggestions:
        return False
    if results_status == "error":
        return False
    # Always show on empty results — this is the primary use case
    if results_status == "empty":
        return True
    # On ok results, only show if there are related alternatives (don't clutter direct answers)
    has_related = any(
        s.get("suggestion_reason") == "related_alternative" for s in suggestions
    )
    return has_related


def _format_suggestions_block(suggestions: List[Dict[str, Any]]) -> str:
    """
    Format suggestion chips as a clean user-facing text block.
    Direct matches shown first (already sorted by relevance_score from views agent).
    Returns empty string if no suggestions.
    """
    if not suggestions:
        return ""

    direct = [s for s in suggestions if s.get("suggestion_reason") == "direct_match"]
    related = [s for s in suggestions if s.get("suggestion_reason") != "direct_match"]

    lines: List[str] = []

    if direct:
        lines.append("\n\n**You might also find these helpful:**")
        for s in direct:
            lines.append(f"- **{s['display_label']}** — {s.get('description', '')}")

    if related:
        lines.append("\n\n**Related topics you can explore:**")
        for s in related:
            lines.append(f"- **{s['display_label']}** — {s.get('description', '')}")

    return "\n".join(lines)


# ===========================================================================
# Helpers
# ===========================================================================


def _safe_serialize_rows(rows: List[Any], max_rows: int) -> List[Dict[str, Any]]:
    safe: List[Dict[str, Any]] = []
    for row in rows[:max_rows]:
        try:
            if isinstance(row, dict):
                safe.append(
                    {
                        k: (
                            v
                            if isinstance(v, (str, int, float, bool, type(None)))
                            else str(v)
                        )
                        for k, v in row.items()
                    }
                )
            else:
                safe.append({"_value": str(row)})
        except Exception:
            safe.append({"_value": "unreadable_row"})
    return safe


def _build_results_summary(
    rows: List[Any],
    rowcount: int,
    error: Optional[str],
) -> Dict[str, Any]:
    if error:
        return {
            "status": "error",
            "message": "An error occurred while retrieving the data.",
        }
    if rowcount == 0:
        return {"status": "empty", "record_count": 0, "data": []}
    sample = _safe_serialize_rows(rows, _MAX_RESULT_ROWS_IN_PROMPT)
    return {
        "status": "ok",
        "record_count": rowcount,
        "showing": len(sample),
        "data": sample,
    }


def _extract_execution_info(
    state: Dict[str, Any],
) -> tuple[List[Any], int, Optional[str]]:
    exec_analysis = state.get("execution_analysis")
    if exec_analysis is None:
        exec_analysis = {}
    if isinstance(exec_analysis, dict) and exec_analysis:
        rows = exec_analysis.get("sample_rows") or []
        rowcount = exec_analysis.get("rowcount") or 0
        error = exec_analysis.get("error")
        return rows, rowcount, error

    exec_result = state.get("execution_result")
    if exec_result is None:
        exec_result = {}
    if isinstance(exec_result, dict):
        rows = exec_result.get("rows") or []
        rowcount = (
            exec_result.get("rowcount")
            if exec_result.get("rowcount") is not None
            else len(rows)
        )
        error = exec_result.get("error")
        return rows, int(rowcount), error

    return [], 0, None


def _extract_constructed_query(state: Dict[str, Any]) -> str:
    construct = state.get("construct") or {}
    if isinstance(construct, dict):
        return construct.get("constructed_query", "") or ""
    if hasattr(construct, "constructed_query"):
        return construct.constructed_query or ""
    return state.get("refined_query") or ""


def _trim_history(
    history: List[Dict[str, str]], max_turns: int
) -> List[Dict[str, str]]:
    if isinstance(history, str):
        try:
            parsed_history = json.loads(history)
        except json.JSONDecodeError:
            return []
        history = parsed_history if isinstance(parsed_history, list) else []

    safe = [
        {
            "role": h.get("role", "user") if isinstance(h, dict) else "user",
            "content": h.get("content", "") if isinstance(h, dict) else str(h),
        }
        for h in history
        if isinstance(h, dict) and h.get("role") in ("user", "assistant")
    ]
    return safe[-max_turns:]


def _build_user_prompt(
    user_query: str,
    constructed_query: str,
    results_summary: Dict[str, Any],
    history: List[Dict[str, str]],
    schema_summary: _SchemaSummary,
) -> str:
    payload: Dict[str, Any] = {
        "user_raw_query": user_query,
        "constructed_query": constructed_query,
        "results_summary": results_summary,
        "conversation_history": history,
    }
    if schema_summary.tables:
        payload["_internal_schema_hint"] = schema_summary.tables
    return json.dumps(payload, ensure_ascii=False)


def _append_response_log(entry: Dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with RESPONSE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ===========================================================================
# Main Node
# ===========================================================================


def response_generator_node(
    llm: BaseLLM,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    state_data = _normalize_state(state)
    user_query = str(state_data.get("user_query", "")).strip()
    if not user_query:
        return {**state_data, "response_error": "no_user_query"}

    # ── Read intent from state ────────────────────────────────────────
    intent_data = state_data.get("intent") or {}
    if isinstance(intent_data, str):
        try:
            parsed_intent = json.loads(intent_data)
        except json.JSONDecodeError:
            parsed_intent = {}
        intent_data = parsed_intent if isinstance(parsed_intent, dict) else {}
    elif not isinstance(intent_data, dict):
        intent_data = {}
    intent = intent_data.get("intent", "SQL_QUERY")
    route_to = intent_data.get("route_to", "QueryTranslation")

    history = _trim_history(state_data.get("history") or [], _MAX_HISTORY_TURNS)

    # ── Extract view suggestions (available on all paths) ─────────────
    view_suggestions = _extract_view_suggestions(state_data)

    # ── PATH 1: Conversational (no SQL results involved) ──────────────
    if route_to == "Generate":
        conversational_prompts = {
            "GREETING": "Respond warmly and naturally to the user's greeting.",
            "EXPLAIN": "Explain the previous result or query in plain language.",
            "SUMMARIZE": "Summarize the conversation or previous results clearly.",
            "NEEDS_CLARITY": "Politely ask the user to clarify their request.",
        }
        instruction = conversational_prompts.get(intent, "Respond helpfully.")

        user_prompt = json.dumps(
            {
                "user_raw_query": user_query,
                "conversation_history": history,
                "instruction": instruction,
            },
            ensure_ascii=False,
        )

        try:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response_node_output",
                    "schema": ResponseNodeOutput.model_json_schema(),
                },
            }

            raw_response = llm.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_format=response_format,
                json_mode=True,
            )
        except Exception as exc:
            logger.error("LLM failed on conversational path: %s", exc)
            return {**state_data, "response_error": str(exc)}

        # Append suggestions on conversational path too if relevant
        # (e.g. user said "show me attendance" but no SQL ran yet)
        suggestions_block = (
            _format_suggestions_block(view_suggestions) if view_suggestions else ""
        )

        # Accept structured or raw responses
        if isinstance(raw_response, (dict, list)):
            resp_obj = (
                raw_response if isinstance(raw_response, dict) else raw_response[0]
            )
            user_text = str(resp_obj.get("response", "")).strip()
        else:
            try:
                parsed = json.loads(raw_response)
                user_text = str(parsed.get("response", "")).strip()
            except Exception:
                user_text = str(raw_response).strip()

        final_response = user_text + suggestions_block

        pretty_log(
            "ResponseNode:conversational",
            state=state_data,
            llm_metrics={"token_breakdown": {}, "latency_ms": None},
            extra={
                "suggestions_shown": (
                    [s["view_name"] for s in view_suggestions]
                    if suggestions_block
                    else []
                )
            },
        )

        return {
            **state_data,
            "user_facing_response": final_response,
            "response_token_breakdown": {},
            "view_suggestions_shown": (
                [s["view_name"] for s in view_suggestions] if suggestions_block else []
            ),
        }

    # ── PATH 2: SQL result path ───────────────────────────────────────
    constructed_query = _extract_constructed_query(state_data)
    rows, rowcount, error = _extract_execution_info(state_data)
    schema_summary = _SchemaSummary.from_raw_schemas(
        state_data.get("retrieved_schemas") or []
    )
    results_summary = _build_results_summary(rows, rowcount, error)
    results_status = results_summary["status"]

    user_prompt = _build_user_prompt(
        user_query, constructed_query, results_summary, history, schema_summary
    )
    prompt_tokens = count_tokens(_SYSTEM_PROMPT + user_prompt)

    try:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "response_node_output",
                "schema": ResponseNodeOutput.model_json_schema(),
            },
        }

        raw_response = llm.generate(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_format=response_format,
            json_mode=True,
        )
    except Exception as exc:
        logger.error("LLM response generation failed: %s", exc)
        return {**state_data, "response_error": str(exc)}
    # ── Append view suggestions when appropriate ──────────────────────
    suggestions_block = ""
    shown_suggestion_names: List[str] = []

    if _should_show_suggestions(view_suggestions, results_status):
        suggestions_block = _format_suggestions_block(view_suggestions)
        shown_suggestion_names = [s["view_name"] for s in view_suggestions]
        logger.info(
            "Appending %d view suggestion(s) to response (results_status=%s)",
            len(view_suggestions),
            results_status,
        )

    # Accept structured or raw responses
    if isinstance(raw_response, (dict, list)):
        resp_obj = raw_response if isinstance(raw_response, dict) else raw_response[0]
    else:
        try:
            resp_obj = json.loads(raw_response)
        except Exception:
            # fallback: treat entire raw_response as the text
            resp_obj = {
                "response": str(raw_response),
                "token_breakdown": {},
                "is_empty_result": results_status == "empty",
                "is_error": results_status == "error",
            }

    user_text = str(resp_obj.get("response", "")).strip()
    final_response = user_text + suggestions_block

    # token accounting
    if isinstance(raw_response, (dict, list)):
        completion_tokens = count_tokens(json.dumps(raw_response, ensure_ascii=False))
    else:
        completion_tokens = count_tokens(str(raw_response))
    total_tokens = prompt_tokens + completion_tokens
    token_breakdown = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }

    _append_response_log(
        {
            "user_query": user_query,
            "constructed_query": constructed_query,
            "results_summary": results_summary,
            "history_turns": len(history),
            "schema_tables": list(schema_summary.tables.keys()),
            "response_preview": final_response[:300],
            "token_breakdown": token_breakdown,
            "is_empty_result": results_status == "empty",
            "is_error": results_status == "error",
            "view_suggestions_count": len(view_suggestions),
            "view_suggestions_shown": shown_suggestion_names,
        }
    )

    return {
        **state_data,
        "user_facing_response": final_response,
        "response_token_breakdown": token_breakdown,
        "view_suggestions_shown": shown_suggestion_names,
    }


__all__ = [
    "ResponseNodeOutput",
    "response_generator_node",
]
