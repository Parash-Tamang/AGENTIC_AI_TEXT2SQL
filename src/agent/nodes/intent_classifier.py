from __future__ import annotations

import json
import re
from typing import Any, Optional
from pydantic import BaseModel
from src.agent.llm.base import BaseLLM
from src.agent.utils.pretty_print import pretty_log
from src.agent.prompt.intent_prompt import INTENT_CLASSIFIER_SYSTEM
from src.agent.utils.prompt_utils import resolve_system_prompt

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VALID_INTENTS = {"SQL_QUERY", "EXPLAIN", "SUMMARIZE", "GREETING", "NEEDS_CLARITY"}

VALID_ROUTES = {
    "QueryTranslation",
    "Generate",
}

VALID_FORMATS = {"NL", "REPORT", "GRAPH", "EXCEL"}
VALID_GRAPH_TYPES = {"LINE", "BAR", "PIE", "SCATTER"}

INTENT_ROUTE_MAP = {
    "SQL_QUERY": "QueryTranslation",
    "EXPLAIN": "Generate",
    "SUMMARIZE": "Generate",
    "GREETING": "Generate",
    "NEEDS_CLARITY": "Generate",
}

# Explicit markers for output format and graph type
EXCEL_MARKER = "/excel"
GRAPH_MARKER = "/graph"


# ─────────────────────────────────────────────────────────────────────────────
# Output dataclass  (what the node writes into state["intent"])
# ─────────────────────────────────────────────────────────────────────────────


class IntentClassifierOutput(BaseModel):
    intent: str
    route_to: str
    confidence: float
    output_format: str | None = None
    graph_type: str | None = None
    reasoning: str

    def __str__(self) -> str:
        fmt = f"\nOutputFormat    : {self.output_format}" if self.output_format else ""
        gtype = f"\nGraphType       : {self.graph_type}" if self.graph_type else ""
        return (
            f"Intent          : {self.intent}\n"
            f"RouteTo         : {self.route_to}\n"
            f"Confidence      : {self.confidence}"
            f"{fmt}{gtype}\n"
            f"Reasoning       : {self.reasoning}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────────────────


class IntentClassifier:
    """
    Classifies a refined query into intent, route, and output format.

    Instantiate once. Call classify() per turn.

    Usage:
        classifier = IntentClassifier(llm=your_llm)
        output = classifier.classify(
            constructed_query = state["refined_query"],
            domain_context    = state.get("domain_context"),
        )
        state["intent"] = output.to_dict()
    """

    def __init__(
        self,
        llm: BaseLLM,
        confidence_threshold: float = 0.6,
        system_prompt: str = INTENT_CLASSIFIER_SYSTEM,
    ):
        self.llm = llm
        self.confidence_threshold = confidence_threshold
        self.system_prompt = system_prompt

    # ── public ───────────────────────────────────────────────────────────────

    def classify(
        self,
        constructed_query: str,
        domain_context: str | None = None,
    ) -> IntentClassifierOutput:
        """
        Classify a refined query.

        Args:
            constructed_query : output of QueryRefiner — clean, self-contained query
            history           : conversation history [{"role": ..., "content": ...}]
            domain_context    : e.g. "school management system"
            schema_entities   : e.g. ["students", "attendance", "fees", "teachers"]
            has_prior_result  : True if data is already displayed to user

        Returns:
            IntentClassifierOutput — write .to_dict() into state["intent"]
        """
        raw = self._call_llm(constructed_query, domain_context)
        result = self._parse(raw)
        result = self._validate(result, constructed_query)

        return result

    # ── private: llm ─────────────────────────────────────────────────────────

    def _call_llm(self, constructed_query: str, domain_context: str | None) -> str:
        user_prompt = json.dumps(
            {
                "ConstructedQuery": constructed_query,
                "DomainContext": domain_context or "general",
            },
            ensure_ascii=False,
        )
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "intent_classifier",
                "schema": IntentClassifierOutput.model_json_schema(),
            },
        }

        return self.llm.generate(
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
            response_format=response_format,
            json_mode=True,
        )

    # ── private: parse ───────────────────────────────────────────────────────

    def _parse(self, raw: str) -> IntentClassifierOutput:
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

            intent = data.get("intent") or data.get("Intent") or "SQL_QUERY"
            confidence = float(data.get("confidence") or data.get("Confidence") or 0.0)
            output_format = (
                data.get("output_format") or data.get("OutputFormat") or None
            )
            graph_type = data.get("graph_type") or data.get("GraphType") or None

            # enforce nulls for non SQL_QUERY
            if intent != "SQL_QUERY":
                output_format = None
                graph_type = None

            # enforce null graph_type when not a graph
            if output_format != "GRAPH":
                graph_type = None

            # validate values
            intent = intent if intent in VALID_INTENTS else "SQL_QUERY"
            output_format = output_format if output_format in VALID_FORMATS else None
            graph_type = graph_type if graph_type in VALID_GRAPH_TYPES else None

            # derive route from intent
            route_to = self._derive_route(intent)

            return IntentClassifierOutput(
                intent=intent,
                route_to=route_to,
                confidence=confidence,
                output_format=output_format,
                graph_type=graph_type,
                reasoning=data.get("reasoning") or data.get("Reasoning") or "",
            )

        except Exception:
            return IntentClassifierOutput(
                intent="SQL_QUERY",
                route_to="QueryTranslation",
                confidence=0.0,
                output_format="NL",
                graph_type=None,
                reasoning="JSON parse failed — defaulting to SQL_QUERY with NL output.",
            )

    # ── private: validate ────────────────────────────────────────────────────

    def _validate(
        self, result: IntentClassifierOutput, constructed_query: str
    ) -> IntentClassifierOutput:
        # 1. always re-derive route — never trust LLM route
        result.route_to = self._derive_route(result.intent)

        # 2. low confidence → route to clarification
        if result.confidence < self.confidence_threshold:
            result.intent = "NEEDS_CLARITY"
            result.route_to = "ClarificationAgent"
            result.reasoning = (
                f"[Low confidence: {result.confidence:.2f}] {result.reasoning}"
            )
            return result

        # 3. SQL_QUERY missing output_format → infer using regex
        if result.intent == "SQL_QUERY" and result.output_format is None:
            result.output_format = self._infer_output_format(constructed_query)

        # 4. GRAPH missing graph_type → infer using regex
        if result.output_format == "GRAPH" and result.graph_type is None:
            result.graph_type = self._infer_graph_type(constructed_query)

        return result

    # ── private: helpers ─────────────────────────────────────────────────────

    def _derive_route(self, intent: str) -> str:
        """Derive route from intent: QueryTranslation for SQL_QUERY, Generate for all others."""
        return INTENT_ROUTE_MAP.get(intent, "Generate")

    # prior-result and history detection removed — classifier no longer relies on conversation state

    def _infer_output_format(self, query: str) -> str | None:
        """Detect explicit markers only: /excel or /graph."""
        if EXCEL_MARKER in query:
            return "EXCEL"
        if GRAPH_MARKER in query:
            return "GRAPH"
        return None

    def _infer_graph_type(self, query: str) -> str | None:
        """Default to BAR when /graph is present."""
        if GRAPH_MARKER in query:
            return "BAR"
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph Node
# ─────────────────────────────────────────────────────────────────────────────


def intent_classifier_node(llm: BaseLLM, state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node for intent classification.

    Reads from state:
        refined_query    : str
        domain_context   : str | None
        prompt_client    : AgentPromptClient | None (optional, fetches prompt from API)

    Writes to state:
        intent           : dict                ← IntentClassifierOutput.to_dict()
    """
    # Resolve system prompt using shared helper (prefers prompt_client)
    system_prompt = resolve_system_prompt(
        state, "intent_classifier", INTENT_CLASSIFIER_SYSTEM
    )

    classifier = IntentClassifier(
        llm=llm, confidence_threshold=0.6, system_prompt=system_prompt
    )

    output = classifier.classify(
        constructed_query=state["refined_query"],
        domain_context=state.get("domain_context"),
    )

    state["intent"] = output.model_dump()
    # Pretty print concise intent summary
    try:
        pretty_log(
            "IntentClassifier",
            state={"refined_query": state.get("refined_query")},
            llm_metrics={"token_breakdown": {}, "latency_ms": None},
            extra={"intent": output.intent, "confidence": output.confidence},
        )
    except Exception:
        pass

    return state


# ─────────────────────────────────────────────────────────────────────────────
# Router  (used in graph.add_conditional_edges)
# ─────────────────────────────────────────────────────────────────────────────


def intent_router(state: dict[str, Any]) -> str:
    """
    LangGraph conditional edge router.
    Reads state["intent"]["route_to"] and returns the next node name.
    """
    return state["intent"]["route_to"]


# state = {}
# state["refined_query"] = "how many sales did we have last month? /graph"
# state["domain_context"] = "retail sales database"
# print(intent_classifier_node(state))
# from src.agent.llm.registry import get_llm

# llm = get_llm("openai/gpt-oss-20b")
# classifier = IntentClassifier(llm=llm)
# output = classifier.classify(
#     constructed_query=state["refined_query"],
#     domain_context=state.get("domain_context"),
# )
# # state["intent"] = output.to_dict()
