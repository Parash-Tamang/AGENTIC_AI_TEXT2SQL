"""
Post-Execution SQL Validator  (Pydantic v2)
===========================================

Single-file module combining three stages of post-execution validation:

1. ``analyze_execution_result``
   Deterministic flags from raw rows:
   empty_result, duplicate_rows, join_explosion, error.

2. ``decide_self_rag_retry``
   Deterministic scoring (0-100) + retry decision from
   structural + semantic + execution signals.

3. ``sql_post_execution_validator_node``
   Orchestrates the full pipeline:
   analyze -> LLM semantic check -> Self-RAG decision -> log.

All inputs and outputs are typed Pydantic v2 models.

Usage
-----
    from sql_post_execution_validator import (
        RawExecutionResult,
        PipelineState,
        sql_post_execution_validator_node,
    )

    state = sql_post_execution_validator_node(
        llm=my_llm,
        state=PipelineState(
            user_query="Total sales per region",
            generated_sql="SELECT region, SUM(amount) FROM sales GROUP BY region",
            retrieved_schemas=[...],
            join_paths=[...],
        ),
        execution_result=RawExecutionResult(
            rows=[{"region": "North", "sum": 1200}],
            rowcount=1,
        ),
    )

    print(state.self_rag_decision.model_dump())
    # {
    #   "overall_valid":  True,
    #   "overall_score":  95,
    #   "self_rag_retry": False,
    #   "reasoning":      "All critical validations passed. Overall score 95.",
    #   "issues":         [],
    # }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

LOG_DIR = Path(__file__).resolve().parent / "logs"
SQL_VALIDATION_LOG = LOG_DIR / "sql_post_execution_validation.jsonl"
from src.agent.nodes.state import get_fetched_views
from src.agent.llm.base import BaseLLM
from src.agent.prompt.sql_results_validator import SQL_RESULTS_VALIDATOR_SYSTEM
from src.agent.utils.pretty_print import pretty_log
from src.agent.utils.prompt_utils import resolve_system_prompt

# ---------------------------------------------------------------------------
# Token counting - graceful fallback when tiktoken is unavailable
# ---------------------------------------------------------------------------
try:
    import tiktoken as _tiktoken

    def _count_tokens(text: str, model: str = "gpt-4") -> int:
        try:
            enc = _tiktoken.encoding_for_model(model)
        except KeyError:
            enc = _tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))

except ImportError:

    def _count_tokens(text: str, model: str = "gpt-4") -> int:  # type: ignore[misc]
        return len(text) // 4


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_JOIN_EXPLOSION_MULTIPLIER = 10
_DUPLICATE_ROW_THRESHOLD = 0.2

_CRITICAL_PENALTIES: Dict[str, int] = {
    "syntax_error": 50,
    "missing_tables": 40,
    "missing_columns": 30,
    "aggregation_issues": 30,
    "semantic_invalid": 40,
    "semantic_critical": 30,
    "execution_error": 50,
    "empty_result": 40,
}

_CRITICAL_ISSUE_KEYS = frozenset(
    {
        "syntax_error",
        "missing_tables",
        "missing_columns",
        "aggregation_issues",
        "semantic_invalid",
        "semantic_critical",
        "execution_error",
        "empty_result",
    }
)


# ===========================================================================
# Pydantic v2 Models
# ===========================================================================


class RawExecutionResult(BaseModel):
    """Raw output from the SQL executor, before any analysis."""

    rows: List[Dict[str, Any]] = Field(
        default_factory=list, description="Result rows as list of dicts"
    )
    rowcount: Optional[int] = Field(
        default=None, description="Total row count; inferred from rows if None"
    )
    error: Optional[str] = Field(
        default=None, description="Execution error message, if any"
    )

    @model_validator(mode="after")
    def infer_rowcount(self) -> "RawExecutionResult":
        if self.rowcount is None:
            self.rowcount = len(self.rows)
        return self


class ExecutionAnalysis(BaseModel):
    """Deterministic flags computed from RawExecutionResult."""

    rowcount: int = Field(description="Total number of rows returned")
    empty_result: bool = Field(description="True when rowcount == 0 and no error")
    duplicate_rows: bool = Field(description="True when >= 20% of rows are duplicates")
    join_explosion: bool = Field(
        description="True when rowcount vastly exceeds expected"
    )
    error: Optional[str] = Field(default=None, description="Execution error, if any")
    sample_rows: List[Dict[str, Any]] = Field(
        default_factory=list, description="Up to 5 serialisable sample rows"
    )


class StructuralValidation(BaseModel):
    """AST / schema-based pre-execution validation result (produced upstream)."""

    syntax_valid: Optional[bool] = Field(default=None)
    missing_tables: List[str] = Field(default_factory=list)
    missing_columns: List[str] = Field(default_factory=list)
    aggregation_issues: List[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class SemanticValidation(BaseModel):
    """LLM-produced semantic validation result."""

    valid: bool = Field(description="Are results semantically correct?")
    score: float = Field(ge=0.0, le=1.0, description="Confidence 0..1")
    issues: List[str] = Field(default_factory=list)
    reasoning: str = Field(default="")
    retry: bool = Field(default=False)
    raw: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, v: Any) -> float:
        return max(0.0, min(1.0, float(v or 0.0)))


class SelfRAGDecision(BaseModel):
    """Final deterministic Self-RAG retry decision."""

    overall_valid: bool = Field(description="True when no retry is needed")
    overall_score: int = Field(
        ge=0, le=100, description="Composite quality score 0-100"
    )
    self_rag_retry: bool = Field(
        description="True when regeneration should be triggered"
    )
    reasoning: str = Field(description="Human-readable explanation of the decision")
    issues: List[str] = Field(default_factory=list)


class TokenBreakdown(BaseModel):
    """LLM token usage for the validation call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @model_validator(mode="after")
    def compute_total(self) -> "TokenBreakdown":
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens
        return self


class PipelineState(BaseModel):
    """LangGraph-style state passed through the validation node."""

    # Inputs
    user_query: str = Field(default="")
    generated_sql: str = Field(default="")

    # Schema / context data
    retrieved_schemas: List[Any] = Field(default_factory=list)
    join_paths: List[Any] = Field(default_factory=list)
    views: List[Any] = Field(default_factory=list)
    views_grade: Optional[Dict[str, Any]] = Field(default=None)
    schema_coverage: Optional[Dict[str, Any]] = Field(default=None)
    schema_coverage_history: List[Dict[str, Any]] = Field(default_factory=list)
    retry_feedback: Optional[Dict[str, Any]] = Field(default=None)

    # Optional upstream structural validation
    validation_structural: Optional[StructuralValidation] = Field(default=None)

    # Execution / retry bookkeeping
    execution_result: Optional[Dict[str, Any]] = Field(default=None)
    validation_errors: List[str] = Field(default_factory=list)
    suggested_fix: str = Field(default="")
    view_suggestions: List[Dict[str, Any]] = Field(default_factory=list)

    # Outputs written by the validator node
    execution_analysis: Optional[ExecutionAnalysis] = Field(default=None)
    validation_with_llm: Optional[SemanticValidation] = Field(default=None)
    self_rag_decision: Optional[SelfRAGDecision] = Field(default=None)
    validation_token_breakdown: Optional[TokenBreakdown] = Field(default=None)
    validation_error: Optional[str] = Field(default=None)

    model_config = {"extra": "allow"}


# ===========================================================================
# 1. Execution result analyzer  (deterministic)
# ===========================================================================


def analyze_execution_result(
    raw: RawExecutionResult,
    expected_max_rows: Optional[int] = None,
) -> ExecutionAnalysis:
    """Compute deterministic flags from a RawExecutionResult.

    Args:
        raw:               Validated RawExecutionResult.
        expected_max_rows: If set, rowcount > expected_max_rows * 10 flags join_explosion.

    Returns:
        ExecutionAnalysis with all flags populated.
    """
    rows: List[Any] = raw.rows
    rowcount: int = raw.rowcount  # type: ignore[assignment]  # set by model_validator
    error: Optional[str] = raw.error

    # empty result
    empty_result = (rowcount == 0) and (error is None)

    # duplicate rows
    duplicate_rows = False
    if rows:
        try:
            serialised = [json.dumps(r, sort_keys=True, default=str) for r in rows]
            unique_count = len(set(serialised))
            if unique_count < len(serialised):
                dup_fraction = 1.0 - unique_count / len(serialised)
                duplicate_rows = dup_fraction >= _DUPLICATE_ROW_THRESHOLD
        except Exception:
            pass

    # join explosion
    join_explosion = False
    if expected_max_rows is not None and rowcount > 0:
        join_explosion = rowcount > expected_max_rows * _JOIN_EXPLOSION_MULTIPLIER

    # sample rows (safe serialisation)
    sample: List[Dict[str, Any]] = []
    for r in rows[:5]:
        try:
            if isinstance(r, dict):
                sample.append(
                    {
                        k: (
                            v
                            if isinstance(v, (str, int, float, bool, type(None)))
                            else str(v)
                        )
                        for k, v in r.items()
                    }
                )
            else:
                sample.append({"_raw": str(r)})
        except Exception:
            sample.append({"_raw": "unserializable_row"})

    return ExecutionAnalysis(
        rowcount=rowcount,
        empty_result=empty_result,
        duplicate_rows=duplicate_rows,
        join_explosion=join_explosion,
        error=error,
        sample_rows=sample,
    )


# ===========================================================================
# 2. Self-RAG retry decision  (deterministic)
# ===========================================================================


def _collect_structural_issues(s: StructuralValidation) -> List[str]:
    issues: List[str] = []
    if s.syntax_valid is False:
        issues.append("syntax_error")
    if s.missing_tables:
        issues.append("missing_tables")
    if s.missing_columns:
        issues.append("missing_columns")
    if s.aggregation_issues:
        issues.append("aggregation_issues")
    return issues


def _collect_semantic_issues(s: SemanticValidation) -> List[str]:
    issues: List[str] = []
    for key in ("critical_issues", "concept_gaps"):
        val = s.raw.get(key)
        if val and isinstance(val, list):
            issues.extend([f"semantic_{key}:{i}" for i in val])
    if not s.valid or s.score == 0.0:
        issues.append("semantic_invalid")
    return issues


def _collect_execution_issues(e: ExecutionAnalysis) -> List[str]:
    issues: List[str] = []
    if e.error:
        issues.append("execution_error")
    if e.empty_result:
        issues.append("empty_result")
    if e.duplicate_rows:
        issues.append("duplicate_rows")
    if e.join_explosion:
        issues.append("join_explosion")
    return issues


def decide_self_rag_retry(
    structural: Optional[StructuralValidation] = None,
    semantic: Optional[SemanticValidation] = None,
    execution_analysis: Optional[ExecutionAnalysis] = None,
    confidence_threshold: float = 0.6,
) -> SelfRAGDecision:
    """Deterministic Self-RAG retry decision.

    Args:
        structural:           Pre-execution structural validation (optional).
        semantic:             LLM semantic validation of results.
        execution_analysis:   Deterministic execution flags.
        confidence_threshold: Minimum semantic confidence to act on failures.

    Returns:
        SelfRAGDecision.
    """
    struct_issues = _collect_structural_issues(structural) if structural else []
    sem_issues = _collect_semantic_issues(semantic) if semantic else []
    exec_issues = (
        _collect_execution_issues(execution_analysis)
        if execution_analysis is not None
        else []
    )

    all_issues = struct_issues + sem_issues + exec_issues

    # composite score
    score = 100
    for issue in struct_issues:
        score -= _CRITICAL_PENALTIES.get(issue, 10)
    for issue in sem_issues:
        score -= _CRITICAL_PENALTIES.get(issue.split(":", 1)[0], 10)
    for issue in exec_issues:
        score -= _CRITICAL_PENALTIES.get(issue, 10)
    score = max(0, min(100, score))

    # semantic confidence
    semantic_conf = semantic.score if semantic else 1.0
    semantic_retry_flag = semantic.retry if semantic else False

    # critical failure presence
    critical_present = any(i for i in all_issues if i in _CRITICAL_ISSUE_KEYS)

    # retry decision
    trigger_retry = False
    if critical_present:
        if struct_issues:
            trigger_retry = True
        elif semantic_retry_flag:
            trigger_retry = semantic_conf >= confidence_threshold
        else:
            trigger_retry = semantic_conf >= confidence_threshold

    if "semantic_invalid" in all_issues and semantic_conf >= confidence_threshold:
        trigger_retry = True

    # Force retry when execution produced an error or zero rows — these
    # conditions usually indicate the SQL should be regenerated. Previously
    # empty_result/execution_error could be considered non-fatal when the
    # semantic confidence was low; in practice we prefer to retry the
    # generator to attempt a different SQL.
    if any(k in exec_issues for k in ("execution_error", "empty_result")):
        trigger_retry = True

    # low-confidence semantic only -> do not force retry
    if semantic and not struct_issues and not exec_issues and not semantic_retry_flag:
        if semantic_conf < confidence_threshold:
            trigger_retry = False

    # reasoning
    reasons: List[str] = []
    if struct_issues:
        reasons.append("Structural checks failed: " + ", ".join(struct_issues))
    if sem_issues:
        reasons.append("Semantic checks failed: " + ", ".join(sem_issues))
    if exec_issues:
        reasons.append("Execution checks failed: " + ", ".join(exec_issues))
    if not reasons:
        reasons.append("All critical validations passed.")

    conf_note = (
        f" Overall score {score}. Semantic confidence {semantic_conf:.2f}."
        if semantic
        else f" Overall score {score}."
    )

    return SelfRAGDecision(
        overall_valid=not trigger_retry,
        overall_score=score,
        self_rag_retry=trigger_retry,
        reasoning=" ".join(reasons) + conf_note,
        issues=all_issues,
    )


# ===========================================================================
# 3. LLM helpers
# ===========================================================================


def _format_schemas_for_llm(schemas: List[Any]) -> str:
    if not schemas:
        return "No schemas provided."

    formatted: List[str] = []
    for schema in schemas:
        if isinstance(schema, dict):
            formatted.append(json.dumps(schema, ensure_ascii=False, indent=2))
            continue
        if hasattr(schema, "model_dump"):
            formatted.append(
                json.dumps(schema.model_dump(), ensure_ascii=False, indent=2)
            )
            continue
        formatted.append(str(schema))
    return "\n\n".join(formatted)


def _format_join_paths_for_llm(join_paths: List[Any]) -> str:
    if not join_paths:
        return "No join paths provided."
    return "\n".join(
        json.dumps(jp, ensure_ascii=False) if isinstance(jp, dict) else str(jp)
        for jp in join_paths
    )


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    """Extract and parse the first JSON object from an LLM response."""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("```")
        ).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM response: {raw[:200]!r}")
    return json.loads(text[start : end + 1])


def _append_validation_log(entry: Dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with SQL_VALIDATION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


# ===========================================================================
# 4. Main node - post-execution validation pipeline
# ===========================================================================


def sql_post_execution_validator_node(
    llm: BaseLLM,
    state: dict,
) -> dict:
    logger.info("Post-execution SQL validation started.")

    # ── Read execution_result from state (written by executor_node) ───

    raw_exec = state.get("execution_result")
    if raw_exec is None:
        raw_exec = {}
    execution_result = RawExecutionResult(
        rows=raw_exec.get("rows", []),
        rowcount=raw_exec.get("rowcount"),
        error=raw_exec.get("error"),
    )

    # ── Build PipelineState from state dict ───────────────────────────
    pipeline_state = PipelineState(
        user_query=state.get("user_query", ""),
        generated_sql=state.get("generated_sql", ""),
        retrieved_schemas=state.get("retrieved_schemas", []),
        join_paths=state.get("join_paths", []),
        views=get_fetched_views(state),
        views_grade=state.get("views_grade"),
        schema_coverage=state.get("schema_coverage"),
        schema_coverage_history=state.get("schema_coverage_history", []),
        retry_feedback=state.get("retry_feedback"),
        validation_structural=state.get("validation_structural"),
        validation_errors=state.get("validation_errors", []),
        suggested_fix=state.get("suggested_fix", ""),
    )

    if not pipeline_state.generated_sql:
        logger.error("No generated_sql in state - aborting validation.")
        return {**state, "validation_error": "no_generated_sql"}

    # ── Step 1: deterministic execution analysis ──────────────────────
    exec_analysis = analyze_execution_result(execution_result)

    # ── Step 2: LLM semantic validation ──────────────────────────────
    payload = {
        "UserQuery": pipeline_state.user_query,
        "ExecutedSQL": pipeline_state.generated_sql,
        "Schemas": _format_schemas_for_llm(pipeline_state.retrieved_schemas),
        "JoinPaths": _format_join_paths_for_llm(pipeline_state.join_paths),
        "ExecutionSummary": {
            "rowcount": exec_analysis.rowcount,
            "sample_rows": exec_analysis.sample_rows,
            "error": exec_analysis.error,
        },
    }

    user_prompt = json.dumps(payload, ensure_ascii=False)
    # resolve system prompt for validation
    system_prompt = resolve_system_prompt(
        state, "sql_results_validator", SQL_RESULTS_VALIDATOR_SYSTEM
    )
    prompt_tokens = _count_tokens(system_prompt + user_prompt)

    try:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "semantic_validation",
                "schema": SemanticValidation.model_json_schema(),
            },
        }

        raw_llm_output = llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
            json_mode=True,
        )
    except Exception as exc:
        logger.error("LLM validation call failed: %s", exc)
        return {**state, "validation_error": str(exc)}
    # Compute completion tokens (serialize if dict)
    if isinstance(raw_llm_output, (dict, list)):
        serialized = json.dumps(raw_llm_output, ensure_ascii=False)
        completion_tokens = _count_tokens(serialized)
        parsed_llm = (
            raw_llm_output if isinstance(raw_llm_output, dict) else raw_llm_output[0]
        )
    else:
        completion_tokens = _count_tokens(str(raw_llm_output))
        try:
            parsed_llm = _parse_llm_json(raw_llm_output)
        except Exception as exc:
            logger.error("Failed to parse LLM validation JSON: %s", exc)
            parsed_llm = {
                "valid": False,
                "score": 0.0,
                "issues": ["invalid_llm_json"],
                "reasoning": str(exc),
                "retry": False,
            }

    semantic = SemanticValidation(
        valid=bool(parsed_llm.get("valid")),
        score=float(parsed_llm.get("score") or 0.0),
        issues=parsed_llm.get("issues") or [],
        reasoning=parsed_llm.get("reasoning") or "",
        retry=bool(parsed_llm.get("retry")),
        raw=parsed_llm,
    )

    # ── Step 3: Self-RAG retry decision ───────────────────────────────
    decision = decide_self_rag_retry(
        structural=pipeline_state.validation_structural,
        semantic=semantic,
        execution_analysis=exec_analysis,
        confidence_threshold=0.6,
    )

    token_breakdown = TokenBreakdown(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )

    # ── Step 4: Log ───────────────────────────────────────────────────
    _append_validation_log(
        {
            "input": {
                "user_query": pipeline_state.user_query,
                "generated_sql": pipeline_state.generated_sql,
            },
            "execution_analysis": exec_analysis.model_dump(),
            "llm_raw_output": raw_llm_output,
            "semantic": semantic.model_dump(),
            "decision": decision.model_dump(),
            "token_breakdown": token_breakdown.model_dump(),
        }
    )

    # ── Step 5: Write back to state dict ─────────────────────────────
    # Pretty print a concise terminal summary
    pretty_log(
        "SQLResultsValidator",
        state={
            "user_query": pipeline_state.user_query,
            "generated_sql": pipeline_state.generated_sql,
        },
        llm_metrics={
            "token_breakdown": token_breakdown.model_dump(),
            "latency_ms": None,
        },
        extra={"decision": decision.model_dump()},
    )

    return {
        **state,
        "execution_analysis": exec_analysis.model_dump(),
        "validation_with_llm": semantic.model_dump(),
        "self_rag_decision": decision.model_dump(),
        "validation_token_breakdown": token_breakdown.model_dump(),
        "validation_passed": decision.overall_valid,
        "validation_error": None,
    }


__all__ = [
    "RawExecutionResult",
    "ExecutionAnalysis",
    "StructuralValidation",
    "SemanticValidation",
    "SelfRAGDecision",
    "TokenBreakdown",
    "PipelineState",
    "analyze_execution_result",
    "decide_self_rag_retry",
    "sql_post_execution_validator_node",
]
