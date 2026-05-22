from __future__ import annotations

import inspect
import json
import logging
import sys
import time
import uuid
import traceback
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_WORKFLOW_LOGGER_NAME = "workflow"
_WORKFLOW_LOG_FILE = Path(__file__).resolve().parents[2] / "logs" / "workflow.log"
_TRACE_CONTEXT: ContextVar["WorkflowTrace | None"] = ContextVar(
    "workflow_trace", default=None
)
_STAGE_CONTEXT: ContextVar[str] = ContextVar("workflow_stage", default="request")


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text.split()) * 2)


def _truncate_string(text: str, max_length: int = 4000) -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"... [truncated {len(text) - max_length} chars]"


def _sanitize(value: Any, depth: int = 0, max_depth: int = 5) -> Any:
    if depth >= max_depth:
        return str(value)

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return _truncate_string(value)

    if hasattr(value, "model_dump"):
        try:
            return _sanitize(value.model_dump(), depth + 1, max_depth)
        except Exception:
            return str(value)

    if isinstance(value, dict):
        return {
            str(key): _sanitize(item, depth + 1, max_depth)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        items = list(value)
        return [_sanitize(item, depth + 1, max_depth) for item in items[:20]]

    if hasattr(value, "head") and hasattr(value, "to_dict"):
        try:
            head = value.head(20)
            return {
                "type": type(value).__name__,
                "shape": list(getattr(value, "shape", ())),
                "rows": _sanitize(head.to_dict(orient="records"), depth + 1, max_depth),
            }
        except Exception:
            return str(value)

    if hasattr(value, "to_dict"):
        try:
            return _sanitize(value.to_dict(), depth + 1, max_depth)
        except Exception:
            return str(value)

    return _truncate_string(str(value))


def _workflow_logger() -> logging.Logger:
    logger = logging.getLogger(_WORKFLOW_LOGGER_NAME)
    if getattr(logger, "_structured_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    _WORKFLOW_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    file_handler = logging.FileHandler(_WORKFLOW_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger._structured_configured = True  # type: ignore[attr-defined]
    return logger


def configure_workflow_logging() -> logging.Logger:
    return _workflow_logger()


@dataclass
class WorkflowTrace:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: float = field(default_factory=time.perf_counter)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    stages_completed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


def start_request_trace(metadata: Optional[dict[str, Any]] = None) -> WorkflowTrace:
    trace = WorkflowTrace(metadata=metadata or {})
    _TRACE_CONTEXT.set(trace)
    return trace


def get_request_trace() -> WorkflowTrace | None:
    return _TRACE_CONTEXT.get()


def get_stage() -> str:
    return _STAGE_CONTEXT.get()


def set_stage(stage: str) -> None:
    _STAGE_CONTEXT.set(stage)


def log_event(
    *,
    stage: str,
    event: str,
    input_data: Any = None,
    output_data: Any = None,
    token_counts: Optional[dict[str, int]] = None,
    latency_ms: Optional[float] = None,
    error: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    trace = get_request_trace()
    payload: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "request_id": trace.request_id if trace else None,
        "stage": stage,
        "event": event,
        "input": _sanitize(input_data),
        "output": _sanitize(output_data),
        "tokens": token_counts
        or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "error": error,
    }
    if extra:
        payload.update(_sanitize(extra))
    _workflow_logger().info(json.dumps(payload, ensure_ascii=False, default=str))


def record_token_usage(
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: Optional[int] = None,
) -> dict[str, int]:
    trace = get_request_trace()
    if trace is None:
        total = (
            total_tokens if total_tokens is not None else input_tokens + output_tokens
        )
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
        }

    if total_tokens is None:
        total_tokens = input_tokens + output_tokens

    trace.input_tokens += int(input_tokens)
    trace.output_tokens += int(output_tokens)
    trace.total_tokens += int(total_tokens)

    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
    }


def _extract_usage_tokens(response: Any) -> dict[str, Optional[int]]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")

    if usage is None:
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}

    def _get(obj: Any, key: str) -> Optional[int]:
        if isinstance(obj, dict):
            value = obj.get(key)
        else:
            value = getattr(obj, key, None)
        return int(value) if value is not None else None

    input_tokens = _get(usage, "prompt_tokens") or _get(usage, "input_tokens")
    output_tokens = _get(usage, "completion_tokens") or _get(usage, "output_tokens")
    total_tokens = _get(usage, "total_tokens")

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def log_llm_call(
    *,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    memory: Optional[list[dict[str, str]]] = None,
    tools: Optional[list[dict[str, str]]] = None,
    response: Any = None,
    output_text: str = "",
    started_at: Optional[float] = None,
    error: Optional[BaseException] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    stage = f"{get_stage()}.llm_api_call"
    latency_ms = None
    if started_at is not None:
        latency_ms = (time.perf_counter() - started_at) * 1000.0

    if error is not None:
        log_event(
            stage=stage,
            event="error",
            input_data={
                "provider": provider,
                "model": model,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "memory": memory or [],
                "tools": tools or [],
            },
            error=str(error),
            latency_ms=latency_ms,
            extra=extra,
        )
        return

    usage = _extract_usage_tokens(response)
    if usage["input_tokens"] is None or usage["output_tokens"] is None:
        estimated_input = _count_tokens(system_prompt + "\n" + user_prompt)
        estimated_output = _count_tokens(output_text)
        usage = {
            "input_tokens": usage["input_tokens"] or estimated_input,
            "output_tokens": usage["output_tokens"] or estimated_output,
            "total_tokens": usage["total_tokens"]
            or (usage["input_tokens"] or estimated_input)
            + (usage["output_tokens"] or estimated_output),
        }

    token_counts = record_token_usage(
        input_tokens=int(usage["input_tokens"] or 0),
        output_tokens=int(usage["output_tokens"] or 0),
        total_tokens=int(usage["total_tokens"] or 0),
    )

    log_event(
        stage=stage,
        event="complete",
        input_data={
            "provider": provider,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "memory": memory or [],
            "tools": tools or [],
        },
        output_data={"text": output_text, "response": _sanitize(response)},
        token_counts=token_counts,
        latency_ms=latency_ms,
        extra=extra,
    )


def trace_node(
    stage: str,
    fn: Callable[..., Any],
    *,
    input_builder: Optional[Callable[[dict[str, Any]], Any]] = None,
    output_builder: Optional[Callable[[Any], Any]] = None,
) -> Callable[[dict[str, Any]], Any]:
    async def _wrapped(state: dict[str, Any]) -> Any:
        previous_stage = get_stage()
        set_stage(stage)
        start = time.perf_counter()
        input_data = input_builder(state) if input_builder else state
        log_event(stage=stage, event="start", input_data=input_data)
        try:
            result = fn(state)
            if inspect.isawaitable(result):
                result = await result
            latency_ms = (time.perf_counter() - start) * 1000.0
            output_data = output_builder(result) if output_builder else result
            log_event(
                stage=stage,
                event="complete",
                input_data=input_data,
                output_data=output_data,
                latency_ms=latency_ms,
            )
            trace = get_request_trace()
            if trace is not None:
                trace.stages_completed += 1
            return result
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            log_event(
                stage=stage,
                event="error",
                input_data=input_data,
                error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
                latency_ms=latency_ms,
            )
            raise
        finally:
            set_stage(previous_stage)

    return _wrapped


def finish_request_trace(
    *,
    final_state: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
    status: str = "success",
) -> None:
    trace = get_request_trace()
    if trace is None:
        return

    summary = {
        "request_id": trace.request_id,
        "status": status,
        "stages_completed": trace.stages_completed,
        "token_summary": {
            "input_tokens": trace.input_tokens,
            "output_tokens": trace.output_tokens,
            "total_tokens": trace.total_tokens,
        },
        "final_state": _sanitize(
            {
                "user_query": (
                    (final_state or {}).get("user_query") if final_state else None
                ),
                "generated_sql": (
                    (final_state or {}).get("generated_sql") if final_state else None
                ),
                "user_facing_response": (
                    (final_state or {}).get("user_facing_response")
                    if final_state
                    else None
                ),
                "validation_passed": (
                    (final_state or {}).get("validation_passed")
                    if final_state
                    else None
                ),
                "validation_error": (
                    (final_state or {}).get("validation_error") if final_state else None
                ),
                "sql_errors": (
                    (final_state or {}).get("sql_errors") if final_state else None
                ),
            }
        ),
        "error": error,
        "elapsed_ms": round((time.perf_counter() - trace.started_at) * 1000.0, 2),
    }
    _workflow_logger().info(
        json.dumps(
            {"stage": "request", "event": "summary", **summary},
            ensure_ascii=False,
            default=str,
        )
    )
