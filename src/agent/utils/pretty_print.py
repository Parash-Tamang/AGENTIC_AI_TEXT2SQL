from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Optional pandas import for DataFrame detection; not required at runtime
try:
    import pandas as _pd  # type: ignore
except Exception:
    _pd = None


def _fmt_kv(k: str, v: Any) -> str:
    if isinstance(v, (dict, list)):
        try:
            return f"{k}: {json.dumps(v, ensure_ascii=False)}"
        except Exception:
            return f"{k}: {str(v)}"
    return f"{k}: {v}"


def pretty_log(
    label: str,
    state: Dict[str, Any] | None = None,
    llm_metrics: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    file=sys.stdout,
) -> None:
    """Print a concise, human-readable summary of pipeline state to the terminal.

    Fields shown (when available): timestamp, label, user_query, route/intent,
    generated_sql, status, token breakdown, latency_ms, key state fields.
    """
    ts = datetime.now().isoformat(timespec="seconds")
    lines = []
    lines.append("---")
    lines.append(f"{ts} | {label}")

    if state:
        uq = state.get("user_query") or state.get("constructed_query") or ""
        if uq:
            lines.append(
                _fmt_kv("UserQuery", uq if len(uq) < 200 else uq[:197] + "...")
            )
        route = None
        construct = state.get("construct")
        if isinstance(construct, dict):
            route = construct.get("classification") or construct.get("intent")
        if not route:
            route = (
                state.get("intent", {}).get("route_to")
                if isinstance(state.get("intent"), dict)
                else None
            )
        if route:
            lines.append(_fmt_kv("Route", route))
        gsql = state.get("generated_sql")
        if gsql:
            lines.append(
                _fmt_kv("GeneratedSQL", gsql if len(gsql) < 200 else gsql[:197] + "...")
            )

        # execution/result hints
        exec_analysis = state.get("execution_analysis")
        if exec_analysis is None:
            exec_analysis = state.get("execution_result")
        if exec_analysis is not None:
            # dict-like execution result
            if isinstance(exec_analysis, dict):
                rc = (
                    exec_analysis.get("rowcount")
                    or exec_analysis.get("row_count")
                    or len(exec_analysis.get("rows", []))
                )
                lines.append(_fmt_kv("Rows", rc))
            # pandas DataFrame
            elif _pd is not None and isinstance(exec_analysis, _pd.DataFrame):
                try:
                    rows = int(exec_analysis.shape[0])
                except Exception:
                    rows = "unknown"
                lines.append(_fmt_kv("Rows", rows))
            # list-like results
            elif isinstance(exec_analysis, list):
                lines.append(_fmt_kv("Rows", len(exec_analysis)))
            else:
                # generic fallback: try attributes or len()
                rc = getattr(exec_analysis, "rowcount", None) or getattr(
                    exec_analysis, "row_count", None
                )
                if rc is None:
                    try:
                        rc = len(exec_analysis)
                    except Exception:
                        rc = "unknown"
                lines.append(_fmt_kv("Rows", rc))

    if llm_metrics:
        tb = (
            llm_metrics.get("token_breakdown")
            or llm_metrics.get("tokens")
            or llm_metrics
        )
        if tb:
            lines.append(_fmt_kv("Tokens", tb))
        lat = llm_metrics.get("latency_ms")
        if lat is not None:
            lines.append(_fmt_kv("Latency(ms)", int(lat)))

    if extra:
        for k, v in extra.items():
            lines.append(_fmt_kv(k, v))

    lines.append("---")
    print("\n".join(lines), file=file)
    try:
        file.flush()
    except Exception:
        pass
