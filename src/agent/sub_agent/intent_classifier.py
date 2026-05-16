import json
import re
from enum import Enum

from pydantic import BaseModel, Field

from src.agent.llm.registry import get_llm

# ─────────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────────


class IntentType(str, Enum):
    SQL_QUERY = "SQL_QUERY"
    SCHEMA_QUESTION = "SCHEMA_QUESTION"
    SUMMARIZE = "SUMMARIZE"
    EXPLAIN = "EXPLAIN"
    GREETING = "GREETING"
    GENERAL = "GENERAL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class RouteTarget(str, Enum):
    TASK_CLASSIFIER = "TaskClassifier"
    SCHEMA_RESPONDER = "SchemaResponder"
    SUMMARIZER = "Summarizer"
    EXPLAINER = "Explainer"
    DIRECT_RESPONSE = "DirectResponse"
    LLM_DIRECT = "LLMDirect"
    REJECTION = "Rejection"


class ActionType(str, Enum):
    CLASSIFY_TASKS = "classify_tasks"
    ANSWER_SCHEMA = "answer_schema"
    SUMMARIZE_CONVERSATION = "summarize_conversation"
    EXPLAIN_SQL = "explain_sql"
    DIRECT_RESPONSE = "direct_response"
    LLM_DIRECT = "llm_direct"
    REJECT = "reject"


# ─────────────────────────────────────────────
# PYDANTIC MODELS
# ─────────────────────────────────────────────


class IntentClassifierOutput(BaseModel):
    """Raw output from the LLM Intent Classifier."""

    Intent: IntentType = Field(..., description="Classified intent of the query.")
    Confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0."
    )
    RouteTo: RouteTarget = Field(..., description="Which agent or handler to route to.")
    Reasoning: str = Field(
        ..., description="One-sentence explanation of the classification."
    )


class RoutingDecision(BaseModel):
    """Final routing decision returned to the pipeline."""

    Intent: IntentType = Field(..., description="Classified intent.")
    Confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score.")
    Reasoning: str = Field(..., description="Reasoning behind the classification.")
    next_agent: RouteTarget | None = Field(
        None, description="Next agent to invoke, if any."
    )
    action: ActionType = Field(..., description="Action to perform.")
    input: str | None = Field(None, description="Input to pass to the next agent.")
    direct_response: str | None = Field(
        None, description="Direct response if no agent needed."
    )


# ─────────────────────────────────────────────
# INTENT CLASSIFIER SYSTEM PROMPT
# ─────────────────────────────────────────────

INTENT_CLASSIFIER_SYSTEM = """\
You are an Intent Classifier Agent in a Text-to-SQL multi-agent pipeline.
You receive a refined query from the Query Refiner Agent via "ConstructedQuery".
Your job is to classify the intent of the query and route it to the correct handler.

You are given:
- The ConstructedQuery from the Query Refiner Agent.

Your task:
1. Analyze the ConstructedQuery carefully.
2. Classify the intent into one of the defined categories.
3. Decide which agent or handler should process it next.
4. Provide a confidence score and reasoning.

---

INTENT CATEGORIES:

SQL_QUERY        - Query requires fetching, filtering, aggregating, or joining data from a database.
SCHEMA_QUESTION  - Query asks about table structure, column info, relationships, or database metadata.
SUMMARIZE        - Query asks to summarize, recap, or review previous conversation or results.
EXPLAIN          - Query asks to explain a previously generated SQL query or result.
GREETING         - Query is a greeting, farewell, or general pleasantry with no data intent.
GENERAL          - Query is a general request like poems, jokes, facts, or general knowledge.
OUT_OF_SCOPE     - Query is harmful, abusive, or cannot be answered by any agent.

---

ROUTING RULES:

SQL_QUERY        → route to "TaskClassifier"
SCHEMA_QUESTION  → route to "SchemaResponder"
SUMMARIZE        → route to "Summarizer"
EXPLAIN          → route to "Explainer"
GREETING         → route to "DirectResponse"
GENERAL          → route to "LLMDirect"
OUT_OF_SCOPE     → route to "Rejection"

---

CRITERIA FOR "SQL_QUERY":
- Query asks to get, fetch, retrieve, show, find, list, count, calculate, compare data.
- Query mentions entities like users, orders, sales, products, employees, revenue, etc.
- Query contains conditions like "from Sikkim", "last month", "greater than 1000".
- Query asks for aggregations like total, average, maximum, minimum, percentage.
- Query asks to filter or sort records from any data source.

---

CRITERIA FOR "SCHEMA_QUESTION":
- Query asks what a table is for or what it contains.
- Query asks what columns or fields a table has.
- Query asks how two tables are related or connected.
- Query asks what databases or tables are available.
- Query uses words like "what is this table", "what does X store", "how are X and Y related".

---

CRITERIA FOR "SUMMARIZE":
- Query uses words like summarise, summarize, recap, overview, what happened, what was discussed.
- Query asks about previous conversation, previous results, or earlier outputs.

---

CRITERIA FOR "EXPLAIN":
- Query uses words like explain, what does this mean, why, how does this work, break it down.
- Query refers to a previously generated SQL query or result.

---

CRITERIA FOR "GREETING":
- Query is a greeting like hi, hello, hey, good morning, bye, thank you, thanks.
- Query is a general pleasantry with no data or task intent.
- Query is a meta-request like "what can you do" or "help".

---

CRITERIA FOR "GENERAL":
- Query asks to write a poem, story, joke, or any creative content.
- Query asks general knowledge questions unrelated to the database.
- Query asks for explanations of general concepts, science, history, etc.
- Query is a valid helpful request but has no relation to SQL or database.

---

CRITERIA FOR "OUT_OF_SCOPE":
- Query is harmful, abusive, or inappropriate.
- Query asks for illegal or unethical assistance.
- Query cannot be answered helpfully by any means.

---

EXAMPLES:

Example 1:
ConstructedQuery: "Get all users from Sikkim along with their sales details."
Intent: SQL_QUERY
Confidence: 0.98
RouteTo: TaskClassifier
Reasoning: Query clearly requests data retrieval involving users and sales tables filtered by location.

---

Example 2:
ConstructedQuery: "What is the orders table for?"
Intent: SCHEMA_QUESTION
Confidence: 0.97
RouteTo: SchemaResponder
Reasoning: User is asking about the purpose of a table, not requesting data from it.

---

Example 3:
ConstructedQuery: "Summarise everything from the previous conversation."
Intent: SUMMARIZE
Confidence: 0.97
RouteTo: Summarizer
Reasoning: Query explicitly asks to summarise prior conversation with no SQL data intent.

---

Example 4:
ConstructedQuery: "Explain the SQL query that was just generated."
Intent: EXPLAIN
Confidence: 0.96
RouteTo: Explainer
Reasoning: Query asks for an explanation of a previously generated SQL query.

---

Example 5:
ConstructedQuery: "Hello, how are you?"
Intent: GREETING
Confidence: 1.0
RouteTo: DirectResponse
Reasoning: Query is a casual greeting with no data or task intent.

---

Example 6:
ConstructedQuery: "Write me a poem about the mountains."
Intent: GENERAL
Confidence: 0.97
RouteTo: LLMDirect
Reasoning: Creative writing request unrelated to SQL — handled directly by LLM.

---

Example 7:
ConstructedQuery: "What is the capital of France?"
Intent: GENERAL
Confidence: 0.98
RouteTo: LLMDirect
Reasoning: General knowledge question with no relation to database or SQL.

---

Example 8:
ConstructedQuery: "How do I hack into a database illegally?"
Intent: OUT_OF_SCOPE
Confidence: 0.99
RouteTo: Rejection
Reasoning: Query is harmful and requests illegal assistance.

---

OUTPUT FORMAT (STRICT JSON):
{
  "Intent": "SQL_QUERY" | "SCHEMA_QUESTION" | "SUMMARIZE" | "EXPLAIN" | "GREETING" | "GENERAL" | "OUT_OF_SCOPE",
  "Confidence": float (0.0–1.0),
  "RouteTo": "TaskClassifier" | "SchemaResponder" | "Summarizer" | "Explainer" | "DirectResponse" | "LLMDirect" | "Rejection",
  "Reasoning": "<One-sentence explanation>"
}

---

Instructions:
- Always analyze the full ConstructedQuery before classifying.
- Never route a non-SQL query to TaskClassifier.
- GENERAL is for helpful requests unrelated to SQL — not harmful ones.
- OUT_OF_SCOPE is only for harmful, abusive, or illegal requests.
- Confidence must reflect how clearly the intent was identified.
- Respond strictly in the specified JSON format only.
"""

LLM_DIRECT_SYSTEM = "You are a helpful and friendly conversational assistant. Answer the user's question clearly and directly."

# ─────────────────────────────────────────────
# DIRECT RESPONSE MESSAGES
# ─────────────────────────────────────────────

DIRECT_RESPONSES: dict[RouteTarget, str] = {
    RouteTarget.DIRECT_RESPONSE: "Hello! I'm your data assistant. Ask me anything — data queries, general questions, or anything else!",
    RouteTarget.REJECTION: "I'm sorry, I can't help with that request.",
}

# ─────────────────────────────────────────────
# ROUTING MAP
# ─────────────────────────────────────────────

ROUTING_MAP: dict[RouteTarget, dict] = {
    RouteTarget.TASK_CLASSIFIER: {
        "next_agent": RouteTarget.TASK_CLASSIFIER,
        "action": ActionType.CLASSIFY_TASKS,
        "direct_response": None,
    },
    RouteTarget.SCHEMA_RESPONDER: {
        "next_agent": RouteTarget.SCHEMA_RESPONDER,
        "action": ActionType.ANSWER_SCHEMA,
        "direct_response": None,
    },
    RouteTarget.SUMMARIZER: {
        "next_agent": RouteTarget.SUMMARIZER,
        "action": ActionType.SUMMARIZE_CONVERSATION,
        "direct_response": None,
    },
    RouteTarget.EXPLAINER: {
        "next_agent": RouteTarget.EXPLAINER,
        "action": ActionType.EXPLAIN_SQL,
        "direct_response": None,
    },
    RouteTarget.DIRECT_RESPONSE: {
        "next_agent": None,
        "action": ActionType.DIRECT_RESPONSE,
        "direct_response": DIRECT_RESPONSES[RouteTarget.DIRECT_RESPONSE],
    },
    RouteTarget.LLM_DIRECT: {
        "next_agent": RouteTarget.LLM_DIRECT,
        "action": ActionType.LLM_DIRECT,
        "direct_response": None,
    },
    RouteTarget.REJECTION: {
        "next_agent": None,
        "action": ActionType.REJECT,
        "direct_response": DIRECT_RESPONSES[RouteTarget.REJECTION],
    },
}


# ─────────────────────────────────────────────
# INTENT CLASSIFIER FUNCTION
# ─────────────────────────────────────────────


def classify_intent(
    constructed_query: str, model_name: str | None = None
) -> IntentClassifierOutput:
    """
    Classifies the intent of a ConstructedQuery using get_llm registry.

    Args:
        constructed_query (str): The refined query from the Query Refiner Agent.
        model_name (str | None): Optional model name. Uses DEFAULT_LLM_MODEL if None.

    Returns:
        IntentClassifierOutput: Validated Pydantic model.
    """
    try:
        llm = get_llm()

        response = llm.generate(
            system_prompt=INTENT_CLASSIFIER_SYSTEM,
            user_prompt=constructed_query,
        )

        clean_output = re.sub(r"```json|```", "", response).strip()
        raw = json.loads(clean_output)
        return IntentClassifierOutput(**raw)

    except Exception as e:
        return IntentClassifierOutput(
            Intent=IntentType.OUT_OF_SCOPE,
            Confidence=0.0,
            RouteTo=RouteTarget.REJECTION,
            Reasoning=f"Classifier error: {str(e)} — defaulting to rejection.",
        )


# ─────────────────────────────────────────────
# LLM DIRECT HANDLER
# ─────────────────────────────────────────────


def run_llm_direct(constructed_query: str, model_name: str | None = None) -> str:
    """
    Handles GENERAL intent — passes query directly to LLM via registry.
    No SQL pipeline involved.

    Args:
        constructed_query (str): The user's general query.
        model_name (str | None): Optional model name. Uses DEFAULT_LLM_MODEL if None.

    Returns:
        str: Direct LLM response.
    """
    llm = get_llm(model_name)
    return llm.generate(
        system_prompt=LLM_DIRECT_SYSTEM,
        user_prompt=constructed_query,
    )


# ─────────────────────────────────────────────
# ROUTER FUNCTION
# ─────────────────────────────────────────────


def route_query(
    intent_result: IntentClassifierOutput, constructed_query: str
) -> RoutingDecision:
    """
    Routes the query to the correct next agent based on intent classification.

    Args:
        intent_result (IntentClassifierOutput): Validated output from classify_intent().
        constructed_query (str): The original ConstructedQuery.

    Returns:
        RoutingDecision: Validated Pydantic routing decision.
    """
    route_config = ROUTING_MAP.get(
        intent_result.RouteTo, ROUTING_MAP[RouteTarget.REJECTION]
    )

    return RoutingDecision(
        Intent=intent_result.Intent,
        Confidence=intent_result.Confidence,
        Reasoning=intent_result.Reasoning,
        next_agent=route_config["next_agent"],
        action=route_config["action"],
        input=constructed_query if route_config["next_agent"] else None,
        direct_response=route_config["direct_response"],
    )


# ─────────────────────────────────────────────
# MAIN PIPELINE FUNCTION
# ─────────────────────────────────────────────


def run_intent_classifier(
    constructed_query: str, model_name: str | None = None
) -> RoutingDecision:
    """
    Full Intent Classifier pipeline:
    1. Classifies intent via get_llm registry
    2. Validates output with Pydantic
    3. Routes to correct next agent
    4. Handles GENERAL intent directly via LLMDirect

    Args:
        constructed_query (str): Refined query from Query Refiner Agent.
        model_name (str | None): Optional model name. Uses DEFAULT_LLM_MODEL if None.

    Returns:
        RoutingDecision: Fully validated Pydantic routing decision.
    """
    print(f"\n[IntentClassifier] Input: {constructed_query}")

    # Step 1: Classify + Validate
    intent_result = classify_intent(constructed_query, model_name)
    print(f"[IntentClassifier] Result: {intent_result.model_dump_json(indent=2)}")

    # Step 2: Route + Validate
    routing = route_query(intent_result, constructed_query)
    print(f"[IntentClassifier] Routing to: {routing.next_agent or routing.action}")

    # Step 3: Handle GENERAL directly
    if routing.action == ActionType.LLM_DIRECT and routing.input:
        print(f"[IntentClassifier] Handling GENERAL via LLMDirect...")
        routing.direct_response = run_llm_direct(routing.input, model_name)

    return routing


if __name__ == "__main__":

    test_cases = [
        # SQL queries
        "Get all users from Sikkim along with their sales details.",
        "How many orders were placed last month and what is the total revenue?",
        "Show me the top 5 products by sales.",
        # Schema questions
        "What is the orders table for?",
        "What columns does the users table have?",
        "How are customers and orders related?",
        # Summarize
        "Summarise everything from the previous conversation.",
        "Give me a recap of what we discussed.",
        # Explain
        "Explain the SQL query that was just generated.",
        "What does this query do?",
        # Greeting
        "Hello, how are you?",
        "Thanks, bye!",
        # General
        "Write me a poem about the mountains.",
        "What is the capital of France?",
        "Tell me a joke.",
        # Out of scope
        "How do I hack into a database illegally?",
        "Say something abusive.",
    ]

    print("\n" + "=" * 60)
    print("INTENT CLASSIFIER — TEST RUN")
    print("=" * 60)

    for query in test_cases:
        print(f"\nInput      : {query}")
        result = run_intent_classifier(query)
        print(f"Intent     : {result.Intent}")
        print(f"Confidence : {result.Confidence}")
        print(f"Route To   : {result.next_agent or result.action}")
        print(f"Reasoning  : {result.Reasoning}")
        if result.direct_response:
            print(f"Response   : {result.direct_response[:100]}")
        print("-" * 60)
