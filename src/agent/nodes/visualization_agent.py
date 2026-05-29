"""
Visualization Agent — Altair-based chart generation node.
Drop-in module: enable by wiring into graph, disable by checking intent.graph_type.

Mirrors the sql_refiner.py pattern:
  - Uses local llm() reference via BaseLLM interface
  - Pydantic structured output for chart selection
  - Returns (png_bytes, was_rendered) tuple internally
  - Writes graph_data back to RAGState dict
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Literal, Optional

import altair as alt
import pandas as pd
import vl_convert as vlc
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from src.agent.llm.base import BaseLLM

logger = logging.getLogger(__name__)

VALID_GRAPH_TYPES = {"LINE", "BAR", "PIE", "SCATTER", "HISTOGRAM"}

_GRAPH_TYPE_TO_CHART_TYPE = {
    "LINE": "line",
    "BAR": "bar",
    "PIE": "pie",
    "SCATTER": "scatter",
    "HISTOGRAM": "histogram",
}


# ─────────────────────────────────────────────────────────────────────────────
# Color palette — clean indigo-led scheme, replaces Vega defaults
# ─────────────────────────────────────────────────────────────────────────────

_PALETTE = [
    "#6366f1",  # indigo-500   (primary)
    "#14b8a6",  # teal-500
    "#f59e0b",  # amber-500
    "#f43f5e",  # rose-500
    "#8b5cf6",  # violet-500
    "#10b981",  # emerald-500
]

_FONT = "Inter, system-ui, sans-serif"

_AXIS_CFG = alt.AxisConfig(
    labelColor="#6b7280",
    titleColor="#374151",
    gridColor="#f3f4f6",
    domainColor="#e5e7eb",
    tickColor="#e5e7eb",
    labelFontSize=11,
    titleFontSize=12,
    labelFont=_FONT,
    titleFont=_FONT,
)

_THEME = alt.theme.register(
    "rag_theme",
    enable=True,
)(
    lambda: {
        "config": {
            "font": _FONT,
            "background": "#ffffff",
            "view": {"stroke": "transparent"},
            "axis": _AXIS_CFG.to_dict(),
            "legend": {
                "labelColor": "#6b7280",
                "titleColor": "#374151",
                "labelFont": _FONT,
                "titleFont": _FONT,
            },
            "title": {
                "font": _FONT,
                "fontSize": 14,
                "fontWeight": 500,
                "color": "#111827",
                "anchor": "start",
            },
            "range": {"category": _PALETTE},
            "mark": {"color": _PALETTE[0]},
        }
    }
)

alt.theme.enable("rag_theme")


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic response model
# ─────────────────────────────────────────────────────────────────────────────


class VegaLiteSpec(BaseModel):
    """
    Structured output from the LLM chart-selection call.
    All fields map directly to Altair encoding shortcuts.
    """

    chart_type: Literal[
        "bar", "line", "area", "scatter", "pie", "histogram", "stat_card"
    ] = Field(description="Chart type that best represents this data")

    reasoning: str = Field(
        description="One sentence: why this chart type fits the question and data shape"
    )

    mark: Literal["bar", "line", "point", "arc", "area", "rect"] = Field(
        description="Altair mark type"
    )

    x_field: str = Field(description="Column name for the x-axis or domain")
    x_type: Literal["quantitative", "ordinal", "temporal", "nominal"] = Field(
        description="Altair field type for x"
    )

    y_field: Optional[str] = Field(
        default=None, description="Column name for y-axis measure"
    )
    y_type: Optional[Literal["quantitative", "ordinal", "temporal", "nominal"]] = Field(
        default=None, description="Altair field type for y"
    )

    color_field: Optional[str] = Field(
        default=None, description="Column to use for color grouping, or null"
    )

    title: str = Field(description="Short human-readable chart title")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates  (mirrors sql_refiner.py prompt block style)
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a data visualization expert embedded in a Text-to-SQL pipeline.
Given a user question, the SQL that produced the result, the relevant schema,
and a sample of the result rows, select the best chart type and Altair encoding.

Selection rules:
- "trend / over time / monthly / daily / yearly"  → line or area,  x = temporal
- "compare / rank / top N / by category / versus" → bar,           x = ordinal
- "distribution / spread / histogram"             → histogram,     x = quantitative
- "relationship / correlation / vs"               → scatter,       x+y = quantitative
- "share / proportion / breakdown / percentage"   → pie,           mark = arc
- Single row + single numeric column              → stat_card      (skip chart)
- Never use pie when distinct category count > 7

Return ONLY valid JSON matching the VegaLiteSpec schema with these exact fields:
chart_type, reasoning, mark, x_field, x_type, y_field, y_type, color_field, title\
"""


def _build_user_prompt(
    refined_query: str,
    generated_sql: str,
    sanitised_schema: dict,
    sample_rows: list[dict],
) -> str:
    return (
        f"Question: {refined_query}\n\n"
        f"SQL:\n{generated_sql}\n\n"
        f"Schema (relevant tables):\n{json.dumps(sanitised_schema, indent=2)}\n\n"
        f"Sample data (first 5 rows):\n"
        f"{json.dumps(sample_rows, indent=2, default=str)}"
    )


def _normalize_chart_dataframe(df: pd.DataFrame, vl: VegaLiteSpec) -> pd.DataFrame:
    """Convert Python date/datetime objects into JSON-safe pandas timestamps.

    vl-convert serializes the Vega-Lite spec to JSON. Native Python ``date``
    values can fail that serialization, so temporal fields are normalized before
    chart construction.
    """
    normalised = df.copy()

    for field_name, field_type in ((vl.x_field, vl.x_type), (vl.y_field, vl.y_type)):
        if (
            not field_name
            or field_type != "temporal"
            or field_name not in normalised.columns
        ):
            continue

        try:
            normalised[field_name] = pd.to_datetime(
                normalised[field_name], errors="coerce"
            )
        except Exception:
            # Fall back to ISO-like strings if pandas cannot coerce the column.
            normalised[field_name] = normalised[field_name].map(
                lambda value: (
                    value.isoformat() if hasattr(value, "isoformat") else value
                )
            )

    return normalised


def _extract_intent_graph_type(state: dict[str, Any]) -> Optional[str]:
    intent = state.get("intent") or {}
    if isinstance(intent, dict):
        graph_type = intent.get("graph_type")
        if isinstance(graph_type, str):
            graph_type = graph_type.strip().upper()
            return graph_type if graph_type in VALID_GRAPH_TYPES else None
    return None


def _resolve_requested_chart_type(graph_type: Optional[str]) -> Optional[str]:
    if not graph_type:
        return None
    return _GRAPH_TYPE_TO_CHART_TYPE.get(graph_type)


# ─────────────────────────────────────────────────────────────────────────────
# Chart builders  (one function per mark type, mirrors _build_create_table_block)
# ─────────────────────────────────────────────────────────────────────────────


def _build_bar(df: pd.DataFrame, vl: VegaLiteSpec) -> alt.Chart:
    enc = dict(
        x=alt.X(f"{vl.x_field}:{vl.x_type[0].upper()}", sort="-y"),
        y=alt.Y(f"{vl.y_field}:{(vl.y_type or 'Q')[0].upper()}"),
        tooltip=[vl.x_field, vl.y_field],
    )
    if vl.color_field:
        enc["color"] = alt.Color(
            f"{vl.color_field}:N",
            scale=alt.Scale(range=_PALETTE),
        )
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(**enc)
    )


def _build_line(df: pd.DataFrame, vl: VegaLiteSpec) -> alt.Chart:
    enc = dict(
        x=alt.X(f"{vl.x_field}:{vl.x_type[0].upper()}"),
        y=alt.Y(f"{vl.y_field}:{(vl.y_type or 'Q')[0].upper()}"),
        tooltip=[vl.x_field, vl.y_field],
    )
    if vl.color_field:
        enc["color"] = alt.Color(
            f"{vl.color_field}:N",
            scale=alt.Scale(range=_PALETTE),
        )
    return alt.Chart(df).mark_line(point=True).encode(**enc)


def _build_area(df: pd.DataFrame, vl: VegaLiteSpec) -> alt.Chart:
    enc = dict(
        x=alt.X(f"{vl.x_field}:{vl.x_type[0].upper()}"),
        y=alt.Y(f"{vl.y_field}:{(vl.y_type or 'Q')[0].upper()}"),
        tooltip=[vl.x_field, vl.y_field],
    )
    if vl.color_field:
        enc["color"] = alt.Color(
            f"{vl.color_field}:N",
            scale=alt.Scale(range=_PALETTE),
        )
    return alt.Chart(df).mark_area(opacity=0.85).encode(**enc)


def _build_scatter(df: pd.DataFrame, vl: VegaLiteSpec) -> alt.Chart:
    enc = dict(
        x=alt.X(f"{vl.x_field}:{vl.x_type[0].upper()}"),
        y=alt.Y(f"{vl.y_field}:{(vl.y_type or 'Q')[0].upper()}"),
        tooltip=[vl.x_field, vl.y_field],
    )
    if vl.color_field:
        enc["color"] = alt.Color(
            f"{vl.color_field}:N",
            scale=alt.Scale(range=_PALETTE),
        )
    return alt.Chart(df).mark_point(filled=True, size=80).encode(**enc)


def _build_pie(df: pd.DataFrame, vl: VegaLiteSpec) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_arc(innerRadius=50)
        .encode(
            theta=alt.Theta(f"{vl.y_field}:Q"),
            color=alt.Color(
                f"{vl.x_field}:N",
                scale=alt.Scale(range=_PALETTE),
            ),
            tooltip=[vl.x_field, vl.y_field],
        )
    )


def _build_histogram(df: pd.DataFrame, vl: VegaLiteSpec) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X(
                f"{vl.x_field}:Q",
                bin=alt.Bin(maxbins=30),
                title=vl.x_field,
            ),
            y=alt.Y("count():Q", title="Count"),
            tooltip=[
                alt.Tooltip(f"{vl.x_field}:Q", bin=True),
                alt.Tooltip("count():Q", title="Count"),
            ],
            color=alt.value(_PALETTE[0]),
        )
    )


_CHART_BUILDERS = {
    "bar": _build_bar,
    "line": _build_line,
    "area": _build_area,
    "scatter": _build_scatter,
    "pie": _build_pie,
    "histogram": _build_histogram,
}


# ─────────────────────────────────────────────────────────────────────────────
# LLM call  (mirrors refine_sql() disabled-by-None + try/except pattern)
# ─────────────────────────────────────────────────────────────────────────────


def _call_llm_for_spec(
    viz_llm: BaseLLM,
    refined_query: str,
    generated_sql: str,
    sanitised_schema: dict,
    sample_rows: list[dict],
) -> Optional[VegaLiteSpec]:
    """
    Call the LLM and parse a VegaLiteSpec from its response.
    Returns None on failure so the caller can degrade gracefully.
    """
    user_prompt = _build_user_prompt(
        refined_query, generated_sql, sanitised_schema, sample_rows
    )

    # Use Pydantic response_format for structured output
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "VegaLiteSpec",
            "schema": VegaLiteSpec.model_json_schema(),
            "strict": True,
        },
    }

    try:
        raw: str = viz_llm.generate(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_format=response_format,
        )
    except Exception as exc:
        logger.error("Viz agent LLM call failed: %s", exc)
        return None

    if not raw or not raw.strip():
        logger.warning("Viz agent LLM returned empty response")
        return None

    try:
        # Response should already be valid JSON from structured output
        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        payload = json.loads(cleaned)
        return VegaLiteSpec(**payload)
    except Exception as exc:
        logger.error("VegaLiteSpec parse failed: %s | raw=%s", exc, raw[:300])
        return None


# ─────────────────────────────────────────────────────────────────────────────
# PNG renderer
# ─────────────────────────────────────────────────────────────────────────────


def _render_png(chart: alt.Chart) -> Optional[bytes]:
    try:
        return vlc.vegalite_to_png(
            vl_spec=chart.to_dict(),
            scale=2,
        )
    except Exception as exc:
        logger.error("vl_convert render failed: %s", exc)
        return None


def _encode_png_to_base64(png_bytes: Optional[bytes]) -> Optional[str]:
    if not png_bytes:
        return None
    return base64.b64encode(png_bytes).decode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Public node  (signature mirrors sql_refiner.refine_sql)
# ─────────────────────────────────────────────────────────────────────────────


def visualization_agent_node(
    state: dict[str, Any],
    viz_llm: Optional[BaseLLM] = None,
) -> dict[str, Any]:
    """
    LangGraph node: select chart type via LLM, build Altair chart, render PNG.

    Args:
        state:   RAGState dict (reads construct, generated_sql,
                 sanitised_schema, execution_result)
        viz_llm: BaseLLM instance, or None to disable (graph_data → None)

    Writes:
        state["graph_data"] = {
            "chart_type": str,
            "title":      str,
            "reasoning":  str,
            "image_base64": str | None,
        }
    """

    # ── Disabled path (mirrors sqlcoder_llm=None check) ───────────────────
    if viz_llm is None:
        logger.debug("Visualization agent disabled (viz_llm=None), skipping")
        state["graph_data"] = None
        return state

    # ── 1. Extract inputs from RAGState ───────────────────────────────────
    refined_query = (state.get("construct") or {}).get("constructed_query", "")
    generated_sql = state.get("generated_sql", "")
    sanitised_schema = state.get("sanitised_schema", {})
    execution_result = state.get("execution_result")
    requested_graph_type = _extract_intent_graph_type(state)

    # ── 2. Guard: nothing to visualize ────────────────────────────────────
    if not execution_result:
        logger.debug("Viz agent: execution_result is empty, skipping")
        state["graph_data"] = None
        return state

    rows = execution_result.get("rows") or execution_result.get("data") or []
    if not rows:
        logger.debug("Viz agent: result rows are empty, skipping")
        state["graph_data"] = None
        return state

    if requested_graph_type is None:
        logger.info("Viz agent: no valid graph_type found in intent, skipping")
        state["graph_data"] = None
        return state

    # ── 3. DataFrame + head(5) sample ─────────────────────────────────────
    df = pd.DataFrame(rows)
    sample_rows = df.head(5).to_dict(orient="records")

    # ── 4. LLM → VegaLiteSpec ─────────────────────────────────────────────
    vl = _call_llm_for_spec(
        viz_llm,
        refined_query,
        generated_sql,
        sanitised_schema,
        sample_rows,
    )

    if vl is None:
        state["graph_data"] = None
        return state

    if vl.chart_type != "stat_card":
        requested_chart_type = _resolve_requested_chart_type(requested_graph_type)
        if requested_chart_type and vl.chart_type != requested_chart_type:
            logger.info(
                "Viz agent: intent requested graph_type=%s but LLM selected chart_type=%s",
                requested_graph_type,
                vl.chart_type,
            )

    logger.info(
        "Viz agent selected chart_type=%s | reasoning: %s",
        vl.chart_type,
        vl.reasoning,
    )

    # ── 5. stat_card fast path ────────────────────────────────────────────
    if vl.chart_type == "stat_card":
        scalar = df.iloc[0, 0] if not df.empty else None
        state["graph_data"] = {
            "chart_type": "stat_card",
            "title": vl.title,
            "reasoning": vl.reasoning,
            "value": scalar,
            "image_base64": None,
        }
        return state

    # ── 6. Build Altair chart ─────────────────────────────────────────────
    builder = _CHART_BUILDERS.get(vl.chart_type)
    if builder is None:
        logger.warning("Unknown chart_type=%s, falling back to bar", vl.chart_type)
        builder = _build_bar

    try:
        df = _normalize_chart_dataframe(df, vl)
        chart = builder(df, vl).properties(
            title=vl.title,
            width=700,
            height=400,
        )
    except Exception as exc:
        logger.error("Altair chart build failed: %s", exc)
        state["graph_data"] = None
        return state

    # ── 7. Render PNG via vl-convert ──────────────────────────────────────
    png_bytes = _render_png(chart)
    image_base64 = _encode_png_to_base64(png_bytes)

    # Persist PNG to disk under assets/images/YYYY-MM-DD for easy retrieval
    image_path = None
    if png_bytes:
        try:
            date_folder = datetime.utcnow().strftime("%Y-%m-%d")
            outdir = Path("assets") / "images" / date_folder
            outdir.mkdir(parents=True, exist_ok=True)
            filename = (
                f"chart_{datetime.utcnow().strftime('%H%M%S')}_{uuid4().hex[:8]}.png"
            )
            filepath = outdir / filename
            filepath.write_bytes(png_bytes)
            # store workspace-relative path (POSIX style)
            image_path = filepath.as_posix()
        except Exception as exc:
            logger.error("Failed to save chart PNG to disk: %s", exc)

    # ── 8. Write back to state ────────────────────────────────────────────
    state["graph_data"] = {
        "chart_type": vl.chart_type,
        "requested_graph_type": requested_graph_type,
        "title": vl.title,
        "reasoning": vl.reasoning,
        "image_base64": image_base64,
        "image_path": image_path,
    }
    return state


# ─────────────────────────────────────────────────────────────────────────────
# Router helper  (paste into graph builder)
# ─────────────────────────────────────────────────────────────────────────────


def should_visualize(state: dict[str, Any]) -> bool:
    """Conditional edge for LangGraph: check if graph output was requested."""
    graph_type = _extract_intent_graph_type(state)
    result = graph_type in VALID_GRAPH_TYPES if graph_type else False

    if not result:
        logger.info("Visualization skipped: graph_type is None or False")
    else:
        logger.info("Visualization enabled for graph_type=%s", graph_type)

    return result
