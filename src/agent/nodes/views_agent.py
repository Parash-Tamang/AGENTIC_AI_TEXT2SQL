"""
Views Agent — three roles:
  1. Structural understanding  : views reveal query shape (groupings, pre-joins, intent)
                                 before SQL is written.
  2. Schema context enrichment : view documents are passed to sql_generator alongside
                                 schema so the LLM understands intent + precise columns.
  3. Follow-up suggestions     : after first answer, surface relevant pre-defined views
                                 as chips the user can pick for instant answers.

Uses executor dispatch pattern (same as before) to parallel-fetch views from vector DB.
Tracks query provenance in query_map for suggestion generation.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM
from src.agent.llm.registry import get_llm
from src.agent.tools.executor import dispatch
from src.agent.utils.pretty_print import pretty_log

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────────────────────────────────────


class ViewSuggestion(BaseModel):
    """A pre-defined view surfaced as a follow-up suggestion chip."""

    view_name: str
    display_label: str
    description: str
    source_queries: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    suggestion_reason: str = ""


class ViewsGrade(BaseModel):
    """LLM grading result."""

    answer: str = "no"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    relevant_views_count: int = 0
    total_views: int = 0
    structural_signals: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    related_views: list[str] = Field(default_factory=list)


class ViewWithSources(dict):
    """View dict extended with query provenance tracking."""

    def __init__(self, view_data: dict, source_queries: list[str] | None = None):
        super().__init__(view_data)
        self["source_queries"] = source_queries or []

    def add_source(self, query: str) -> None:
        if query not in self["source_queries"]:
            self["source_queries"].append(query)


class ViewsResult:
    """Deduplicated views container with query_map provenance."""

    def __init__(self):
        self.views_map: dict[str, ViewWithSources] = {}
        self.query_map: dict[str, list[str]] = {}
        self.errors: list[dict] = []

    def add_view(self, query: str, view_data: dict) -> None:
        if not view_data:
            return
        name = view_data.get("view_name") or view_data.get("name", "unknown")
        if name not in self.views_map:
            self.views_map[name] = ViewWithSources(view_data, [query])
        else:
            self.views_map[name].add_source(query)
        self.query_map.setdefault(query, [])
        if name not in self.query_map[query]:
            self.query_map[query].append(name)

    def add_error(self, query: str, error: str) -> None:
        self.errors.append({"query": query, "error": error})

    def to_dict(self) -> dict:
        return {
            "views": list(self.views_map.values()),
            "unique_count": len(self.views_map),
            "query_map": self.query_map,
            "errors": self.errors,
        }


# ─────────────────────────────────────────────────────────────────────────────
# System Prompts
# ─────────────────────────────────────────────────────────────────────────────

_GRADER_SYSTEM = """\
You are a Views Structural Analyst in a Text-to-SQL pipeline.

Given a ConstructedQuery and a list of database views, you must:
1. Identify STRUCTURAL SIGNALS the views reveal about the query shape
   (e.g. "school-level aggregation", "pre-joined student+attendance data",
    "grouped by district", "time-series pattern").
2. Assess coverage: do the views cover ≥80% of query requirements?
3. Decide yes/no and provide confidence 0.0–1.0.
4. Count relevant views.
5. Identify RELATED views: views that are not a direct match but cover
   related domain (e.g. query asks for student grades, a view has student
   attendance — related but not a match). List their view_name values.

OUTPUT FORMAT — strict JSON only, no markdown, no preamble:
{
    "answer": "yes" or "no",
    "confidence": 0.0–1.0,
    "reasoning": "...",
    "relevant_views_count": <int>,
    "structural_signals": ["signal1", "signal2"],
    "recommendations": ["..."],
    "related_views": ["view_name1", "view_name2"]
}

Rules:
- answer "yes" if views cover ≥80% of requirements AND are relevant.
- answer "no" if views don't match but still populate related_views if any exist.
- structural_signals must be concrete query-shape insights, not view names.
- related_views: names of views that partially overlap the query domain.
- Never hallucinate columns or tables not described in the view documents.
"""

_SUGGESTION_SYSTEM = """\
You are a Follow-up Suggestion Generator in a Text-to-SQL pipeline.

Given a list of database views (which may be direct matches OR related views)
and the original user query, generate user-facing suggestion chips so the
user can pick a pre-built view for a better or alternative answer.

Each suggestion must clearly explain WHY this view is being offered —
either as a direct match or as a related alternative the user might find useful.

OUTPUT FORMAT — strict JSON only, no markdown, no preamble:
{
    "suggestions": [
        {
            "view_name": "vAttendanceBySchool",
            "display_label": "Attendance by school",
            "description": "Shows daily attendance rates grouped by school",
            "suggestion_reason": "direct_match" or "related_alternative",
            "relevance_score": 0.0–1.0
        }
    ]
}

Rules:
- Include both direct matches (suggestion_reason: "direct_match") and
  related alternatives (suggestion_reason: "related_alternative").
- Sort by relevance_score descending — direct matches score higher.
- display_label must be short (≤5 words), sentence case.
- description must be one sentence, plain English.
- Maximum 5 suggestions total.
- If truly no views are relevant at all, return {"suggestions": []}.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    return json.loads(cleaned)


def _get_all_queries(state: dict[str, Any]) -> list[str]:
    """
    Extract unique non-empty queries from state.
    Sources: construct.constructed_query + decomposed.sub_queries (if composite).
    """
    candidates: list[str] = []

    # FIX: guard against construct being None
    construct = state.get("construct") or {}
    constructed = (
        construct.get("constructed_query", "") if isinstance(construct, dict) else ""
    )
    if constructed:
        candidates.append(constructed)

    decomposed = state.get("decomposed") or {}
    if isinstance(decomposed, dict) and decomposed.get("is_composite"):
        for sub_q in decomposed.get("sub_queries", []):
            q = (
                sub_q.get("query", "")
                if isinstance(sub_q, dict)
                else getattr(sub_q, "query", "")
            )
            if q:
                candidates.append(q)

    seen: set[str] = set()
    return [q for q in candidates if q not in seen and not seen.add(q)]  # type: ignore[func-returns-value]


def _fetch_views_for_query(query: str, top_k: int) -> tuple[str, list[dict]]:
    """
    Fetch views for one query via executor dispatch.
    FIX: dispatch() returns a dict, not a JSON string — removed json.loads().
    """
    try:
        results = dispatch("fetch_view", {"query": query, "top_k": top_k})

        # dispatch returns a dict or list directly
        if isinstance(results, list):
            return query, results

        if isinstance(results, dict):
            if "error" in results:
                logger.warning(
                    f"fetch_view error for '{query[:50]}': {results['error']}"
                )
                return query, []
            # some dispatch wrappers nest results under a key
            nested = results.get("results") or results.get("views") or []
            if isinstance(nested, list):
                return query, nested
            return query, []

        logger.warning(f"fetch_view unexpected return type: {type(results)}")
        return query, []

    except Exception as exc:
        logger.error(f"Exception fetching views for '{query[:50]}': {exc}")
        return query, []


def _is_follow_up(state: dict[str, Any]) -> bool:
    """Detect follow-up turn from state."""
    construct = state.get("construct") or {}
    classification = (
        construct.get("classification", "FRESH").upper()
        if isinstance(construct, dict)
        else "FRESH"
    )
    return classification in ("FOLLOW_UP", "REFINEMENT", "CONTINUATION")


def _should_generate_suggestions(
    grade: ViewsGrade,
    views: list[dict],
    is_follow_up: bool,
) -> bool:
    """
    Decide whether to generate suggestion chips.

    Generate suggestions when ANY of these are true:
      1. Follow-up turn with matching views.
      2. Fresh query where views matched (grade.answer == "yes").
      3. Fresh query where no views matched BUT related views were found.

    Never generate if there are literally no views fetched at all.
    """
    if not views:
        return False
    if is_follow_up and grade.answer == "yes":
        return True
    if grade.answer == "yes":
        return True
    if grade.related_views:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# LLM calls
# ─────────────────────────────────────────────────────────────────────────────


def _grade_views(
    llm: BaseLLM,
    constructed_query: str,
    views: list[dict],
) -> ViewsGrade:
    """Role 1 — structural understanding."""
    if not views:
        return ViewsGrade(
            answer="no",
            reasoning="No views fetched.",
            errors=["No views available"],
        )

    views_text = "\n".join(
        f"- {v.get('view_name') or v.get('name', 'unknown')}: "
        f"{v.get('document', '')[:400]}"
        for v in views
    )
    user_prompt = (
        f"ConstructedQuery: {constructed_query}\n\n"
        f"Views:\n{views_text}\n\n"
        "Analyse structural signals, assess coverage, and list related_views."
    )

    try:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "views_grade",
                "schema": ViewsGrade.model_json_schema(),
            },
        }

        raw = llm.generate(
            system_prompt=_GRADER_SYSTEM,
            user_prompt=user_prompt,
            response_format=response_format,
            json_mode=True,
        )

        if isinstance(raw, (dict, list)):
            data = raw if isinstance(raw, dict) else raw[0]
        else:
            data = _parse_llm_json(raw)

        # Guard: data must be a dict
        if not isinstance(data, dict):
            raise ValueError(f"Unexpected grader response type: {type(data)}")

        answer = data.get("answer", "no").lower()
        if answer not in ("yes", "no"):
            answer = "no"

        return ViewsGrade(
            answer=answer,
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
            reasoning=data.get("reasoning", ""),
            relevant_views_count=int(data.get("relevant_views_count", 0)),
            total_views=len(views),
            structural_signals=data.get("structural_signals") or [],
            recommendations=data.get("recommendations") or [],
            related_views=data.get("related_views") or [],
            errors=data.get("errors") or [],
        )

    except Exception as exc:
        logger.error(f"Views grader LLM error: {exc}")
        return ViewsGrade(
            answer="no",
            reasoning=f"Grader error: {exc}",
            errors=[str(exc)],
        )


def _generate_suggestions(
    llm: BaseLLM,
    constructed_query: str,
    views: list[dict],
    query_map: dict[str, list[str]],
    related_view_names: list[str],
) -> list[ViewSuggestion]:
    """Role 3 — follow-up suggestion chips."""
    if not views:
        return []

    retrieved_names = {name for names in query_map.values() for name in names}

    direct_views = [
        v for v in views if (v.get("view_name") or v.get("name", "")) in retrieved_names
    ]
    related_views = [
        v
        for v in views
        if (v.get("view_name") or v.get("name", "")) in (related_view_names or [])
        and (v.get("view_name") or v.get("name", "")) not in retrieved_names
    ]

    candidate_views = direct_views + related_views
    if not candidate_views:
        logger.info("No candidate views for suggestions (direct or related)")
        return []

    views_text = "\n".join(
        f"- {v.get('view_name') or v.get('name', 'unknown')} "
        f"[{'direct' if (v.get('view_name') or v.get('name','')) in retrieved_names else 'related'}]: "
        f"{v.get('document', '')[:300]}"
        for v in candidate_views[:10]
    )
    user_prompt = (
        f"UserQuery: {constructed_query}\n\n"
        f"AvailableViews (direct matches and related alternatives):\n{views_text}\n\n"
        "Generate suggestion chips. Mark direct matches with suggestion_reason='direct_match' "
        "and related alternatives with suggestion_reason='related_alternative'."
    )

    try:
        wrapper_schema = {
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": ViewSuggestion.model_json_schema(),
                }
            },
            "required": ["suggestions"],
        }
        response_format = {
            "type": "json_schema",
            "json_schema": {"name": "view_suggestions", "schema": wrapper_schema},
        }

        raw = llm.generate(
            system_prompt=_SUGGESTION_SYSTEM,
            user_prompt=user_prompt,
            response_format=response_format,
            json_mode=True,
        )

        if isinstance(raw, (dict, list)):
            data = raw if isinstance(raw, dict) else (raw[0] if raw else {})
        else:
            data = _parse_llm_json(raw)

        if not isinstance(data, dict):
            raise ValueError(f"Unexpected suggestion response type: {type(data)}")

        suggestions = []
        for s in data.get("suggestions") or []:
            if not isinstance(s, dict):
                continue
            sources = [
                q for q, names in query_map.items() if s.get("view_name") in names
            ]
            try:
                suggestions.append(
                    ViewSuggestion(
                        view_name=s.get("view_name", ""),
                        display_label=s.get("display_label", ""),
                        description=s.get("description", ""),
                        source_queries=sources,
                        relevance_score=float(s.get("relevance_score", 0.0)),
                        suggestion_reason=s.get(
                            "suggestion_reason", "related_alternative"
                        ),
                    )
                )
            except Exception as parse_exc:
                logger.warning(f"Skipping malformed suggestion: {parse_exc}")
                continue

        suggestions.sort(key=lambda s: s.relevance_score, reverse=True)
        logger.info(f"Generated {len(suggestions)} suggestion chips")
        return suggestions

    except Exception as exc:
        logger.error(f"Suggestion generator error: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Node
# ─────────────────────────────────────────────────────────────────────────────


def views_fetcher_node(
    llm: BaseLLM,
    state: dict[str, Any],
    top_k: int = 10,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """
    LangGraph node: fetch views + grade + generate suggestions.

    State keys written:
        state["views"]            : {views, unique_count, query_map, errors}
        state["views_grade"]      : ViewsGrade dict
        state["view_suggestions"] : list[ViewSuggestion dicts]
    """
    logger.info("Views agent starting")

    if llm is None:
        try:
            llm = get_llm()
        except Exception as exc:
            logger.error(f"LLM registry error: {exc}")
            return {
                **state,
                "views": {
                    "views": [],
                    "unique_count": 0,
                    "query_map": {},
                    "errors": [str(exc)],
                },
                "views_grade": ViewsGrade(answer="no", errors=[str(exc)]).model_dump(),
                "view_suggestions": [],
            }

    # FIX: guard construct being None
    construct = state.get("construct") or {}
    constructed_query = (
        construct.get("constructed_query", "") if isinstance(construct, dict) else ""
    )
    queries = _get_all_queries(state)

    if not queries:
        logger.error("No queries in state — views agent returning empty")
        grade = ViewsGrade(
            answer="no", reasoning="No queries in state", errors=["No queries"]
        )
        return {
            **state,
            "views": {
                "views": [],
                "unique_count": 0,
                "query_map": {},
                "errors": ["No queries"],
            },
            "views_grade": grade.model_dump(),
            "view_suggestions": [],
        }

    # ── Parallel fetch ────────────────────────────────────────────────────────
    workers = max_workers or min(len(queries), 4)
    logger.info(f"Fetching views for {len(queries)} queries with {workers} workers")

    views_result = ViewsResult()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_views_for_query, q, top_k): q for q in queries
        }
        for future in as_completed(futures):
            query = futures[future]
            try:
                _, results = future.result()
                logger.debug(
                    f"  fetch_view returned {len(results)} items for '{query[:50]}'"
                )
                for view in results:
                    views_result.add_view(query, view)
            except Exception as exc:
                views_result.add_error(query, str(exc))
                logger.error(f"Fetch error for '{query[:50]}': {exc}")

    views_data = views_result.to_dict()
    logger.info(f"Fetched {views_data['unique_count']} unique views")

    # ── Role 1: structural grading ────────────────────────────────────────────
    grade = _grade_views(llm, constructed_query, views_data["views"])
    logger.info(
        f"Views grade: {grade.answer.upper()} "
        f"(confidence={grade.confidence:.2f}, "
        f"signals={grade.structural_signals}, "
        f"related={grade.related_views})"
    )

    # ── Role 3: suggestions ───────────────────────────────────────────────────
    is_follow_up = _is_follow_up(state)
    suggestions: list[ViewSuggestion] = []

    if _should_generate_suggestions(grade, views_data["views"], is_follow_up):
        reason = (
            "follow-up turn with matching views"
            if is_follow_up and grade.answer == "yes"
            else (
                "direct view match on fresh query"
                if grade.answer == "yes"
                else "no direct match but related views found"
            )
        )
        logger.info(f"Generating suggestion chips ({reason})")
        suggestions = _generate_suggestions(
            llm,
            constructed_query,
            views_data["views"],
            views_data["query_map"],
            grade.related_views,
        )
    else:
        logger.info(
            f"Skipping suggestion generation — views={views_data['unique_count']}, "
            f"grade={grade.answer}, related={grade.related_views}"
        )

    pretty_log(
        "ViewsFetcher",
        state={
            "user_query": state.get("user_query"),
            "constructed_query": constructed_query,
        },
        llm_metrics={"token_breakdown": {}, "latency_ms": None},
        extra={
            "views_count": views_data.get("unique_count", 0),
            "grade": grade.answer,
            "suggestions": [s.view_name for s in suggestions],
        },
    )

    return {
        **state,
        "views": views_data,
        "views_grade": grade.model_dump(),
        "view_suggestions": [s.model_dump() for s in suggestions],
    }
