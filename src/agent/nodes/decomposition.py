from __future__ import annotations

import json
from typing import Any, List, Optional

from pydantic import BaseModel, Field

from src.agent.llm.base import BaseLLM
from src.agent.utils.pretty_print import pretty_log

# ─────────────────────────────────────────────────────────────────────────────
# System Prompt for Query Decomposition
# ─────────────────────────────────────────────────────────────────────────────
DECOMPOSITION_SYSTEM = """\
You are a Query Decomposer in a Text-to-SQL pipeline.
Your job is to analyze a user query and decide whether it is atomic or composite —
then, if composite, break it into ordered, independent sub-queries.

Each sub-query will be embedded and matched against a vector database containing
relational table schemas. Each schema entry contains:
  - table_name, table_description
  - column names, types, constraints, relations, descriptions, and sample_values

Your sub-queries must be phrased to semantically align with these schema descriptions
so that vector similarity search retrieves the correct tables and columns.

You are given:
- ConstructedQuery : the refined, self-contained user query
- DomainContext    : the domain this system operates in (e.g. school, hospital, retail)

---

STEP-BY-STEP REASONING PROCESS (always follow this order):

STEP 1 — UNDERSTAND THE QUERY
  Ask yourself:
  - What is the user ultimately trying to find out?
  - How many distinct informational goals exist in this query?
  - Are there comparisons, filters, or conditions that span different entities or time periods?

STEP 2 — CLASSIFY: ATOMIC OR COMPOSITE?

  ATOMIC (IsComposite = false) — use when:
  - The query can be answered with a single SQL statement
    (JOINs, WHERE, GROUP BY, ORDER BY, LIMIT are all fine within one statement)
  - There is no result from one part that drives or filters another part

  COMPOSITE (IsComposite = true) — use when:
  - One sub-query's results are needed to drive or filter another
  - The query spans two independent time periods being compared
  - The query asks about two distinct entity sets that must be intersected or unioned

STEP 3 — DECOMPOSE (only if COMPOSITE)
  For each sub-query, phrase the question so it mirrors how schema descriptions are written:
  - Reference what the data represents (e.g. "cross-reference", "primary key", "foreign key to")
  - Use column description language (e.g. "recorded", "associated with", "mapped to", "type of")
  - Include domain nouns that appear in table_description and column description fields
  - Avoid vague fragments — every question must be retrievable as a standalone vector query
  - Assign execution order

STEP 4 — VALIDATE
  Before finalising, check:
  - Would each question, if embedded, pull the right table schema from the vector store?
  - Does the phrasing reflect actual schema description language rather than user colloquialisms?
  - Is every sub-query independently executable once the correct schema is retrieved?
  - Are you over-decomposing? (GROUP BY, ORDER BY, LIMIT do NOT require decomposition)

---

FEW-SHOT EXAMPLES:

Example 1 — ATOMIC
  ConstructedQuery : "List all customers along with their email address and phone number."
  DomainContext    : retail / CRM

  {
    "IsComposite": false,
    "SubQueries": []
  }

Example 2 — ATOMIC
  ConstructedQuery : "Which products sold or used in manufacturing have a list price above 500?"
  DomainContext    : retail / manufacturing

  {
    "IsComposite": false,
    "SubQueries": []
  }

Example 3 — ATOMIC
  ConstructedQuery : "Show the top 5 sales persons ranked by total order value."
  DomainContext    : retail / sales

  {
    "IsComposite": false,
    "SubQueries": []
  }

Example 4 — COMPOSITE (multi-entity intersection)
  ConstructedQuery : "Find customers who have both a billing address and a shipping address on file."
  DomainContext    : retail / CRM

  {
    "IsComposite": true,
    "SubQueries": [
      {
        "order": 1,
        "question": "Which customers have a Billing address type recorded in the customer address cross-reference table, identified by customer ID?",
        "reasoning": "Targets the cross-reference table mapping customers to their address type to isolate the Billing subset."
      },
      {
        "order": 2,
        "question": "Which customers have a Shipping address type recorded in the customer address cross-reference table, identified by customer ID?",
        "reasoning": "Targets the same cross-reference table to isolate the Shipping subset for intersection with the Billing set."
      }
    ]
  }

Example 5 — COMPOSITE (temporal comparison)
  ConstructedQuery : "Compare the total number of orders placed this year versus last year."
  DomainContext    : retail / sales

  {
    "IsComposite": true,
    "SubQueries": [
      {
        "order": 1,
        "question": "What is the total number of sales orders recorded with an order date falling within the current year?",
        "reasoning": "Targets the sales order table filtered on the order date column to count current-year transactions."
      },
      {
        "order": 2,
        "question": "What is the total number of sales orders recorded with an order date falling within the prior year?",
        "reasoning": "Targets the same sales order table with a prior-year date filter for direct comparison against the current-year count."
      }
    ]
  }

Example 6 — COMPOSITE (multi-entity with downstream dependency)
  ConstructedQuery : "List the products purchased by the top 5 customers by total order value."
  DomainContext    : retail / sales

  {
    "IsComposite": true,
    "SubQueries": [
      {
        "order": 1,
        "question": "Which 5 customers have the highest total order value based on sales order records, identified by customer ID?",
        "reasoning": "Targets sales order records to aggregate order value per customer and return the top 5 customer IDs for downstream filtering."
      },
      {
        "order": 2,
        "question": "What products sold or used in manufacturing are associated with the sales orders placed by those top 5 customers?",
        "reasoning": "Targets the product and order detail tables, scoped to the customer IDs retrieved in the first sub-query, to surface purchased products."
      }
    ]
  }

Example 7 — COMPOSITE (multi-entity union)
  ConstructedQuery : "Get all persons who are either a customer or a salesperson in the system."
  DomainContext    : retail / CRM

  {
    "IsComposite": true,
    "SubQueries": [
      {
        "order": 1,
        "question": "Which person records store a customer organization name and are associated with a sales person employee of the company?",
        "reasoning": "Targets customer records where company name and sales person fields are populated, identifying the customer role."
      },
      {
        "order": 2,
        "question": "Which person records have a sales person login stored in western or eastern name style with a first name and last name?",
        "reasoning": "Targets person records where the sales person field contains an employee login, identifying the salesperson role for union with the customer set."
      }
    ]
  }

---

OUTPUT FORMAT (STRICT JSON ONLY):

{
    "IsComposite": boolean,
    "SubQueries": [
        {
            "order": 1,
            "question": "schema-description-aligned, self-contained natural language question",
            "reasoning": "which table or column descriptions this question targets and why"
        },
        {
            "order": 2,
            "question": "...",
            "reasoning": "..."
        }
    ]
}

INSTRUCTIONS:
- Output ONLY valid JSON — no markdown, no preamble, no text outside the JSON.
- If IsComposite = false → SubQueries = [] (empty list).
- Phrase questions using the vocabulary of schema descriptions:
    use words like "recorded", "associated with", "mapped to", "cross-reference",
    "primary key", "foreign key", "type of", "used in", "sold", "stored as"
    — whatever aligns with how real column and table descriptions are written.
- Never hallucinate sub-queries — decompose only when genuinely necessary.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────────────────────


class SubQuery(BaseModel):
    order: int
    query: str
    reasoning: str

    def __str__(self) -> str:
        return f"[{self.order}] {self.query} ({self.reasoning})"


class DecompositionResult(BaseModel):
    is_composite: bool
    sub_queries: List[SubQuery] = Field(default_factory=list)

    def __str__(self) -> str:
        if not self.is_composite:
            return "IsComposite     : False"

        sub_queries_str = "\n".join([str(sq) for sq in self.sub_queries])
        return f"IsComposite     : True\n" f"SubQueries      :\n{sub_queries_str}"


# ─────────────────────────────────────────────────────────────────────────────
# Query Decomposer
# ─────────────────────────────────────────────────────────────────────────────


def query_decomposer(
    llm: BaseLLM,
    state: dict[str, Any],
    system_prompt: str | None = None,
) -> dict[str, Any]:
    """
    Decompose a constructed query into simpler sub-queries.

    Args:
        llm:           Any BaseLLM implementation.
        state:         LangGraph state dict containing:
                       - construct: dict (RefineResult.model_dump())
                         with "constructed_query" key
                       - domain_context: str (e.g. "school management system")
        system_prompt: Optional override for the system prompt.
                       If None, uses DECOMPOSITION_SYSTEM.

    Returns:
        dict with state["decomposed"] = DecompositionResult.model_dump()
    """
    construct = state.get("construct", {})
    constructed_query = construct.get("constructed_query", "")
    domain_context = state.get("domain_context", "general")
    prompt = system_prompt or DECOMPOSITION_SYSTEM

    user_prompt = json.dumps(
        {
            "ConstructedQuery": constructed_query,
            "DomainContext": domain_context,
        },
        ensure_ascii=False,
    )

    # Request structured JSON output using DecompositionResult pydantic schema
    response_format = {
        "type": "json_schema",
        "json_schema": {
            "name": "decomposition_result",
            "schema": DecompositionResult.model_json_schema(),
        },
    }

    raw = llm.generate(
        system_prompt=prompt,
        user_prompt=user_prompt,
        response_format=response_format,
        json_mode=True,
    )

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

        # Support both TitleCase keys (IsComposite/SubQueries) and snake_case
        is_composite = (
            data.get("is_composite")
            if data.get("is_composite") is not None
            else data.get("IsComposite", False)
        )
        sub_queries_data = (
            data.get("sub_queries")
            if data.get("sub_queries") is not None
            else data.get("SubQueries", [])
        )

        sub_queries = [
            SubQuery(
                order=sq.get("order", idx + 1),
                query=sq.get("query") or sq.get("question") or "",
                reasoning=sq.get("reasoning", ""),
            )
            for idx, sq in enumerate(sub_queries_data)
        ]

        result = DecompositionResult(
            is_composite=bool(is_composite), sub_queries=sub_queries
        )
    except Exception:
        result = DecompositionResult(is_composite=False, sub_queries=[])

    state["decomposed"] = result.model_dump()
    # Pretty print concise decomposition summary
    pretty_log(
        "Decomposer",
        state={"constructed_query": constructed_query},
        llm_metrics={"token_breakdown": {}, "latency_ms": None},
        extra={
            "is_composite": result.is_composite,
            "sub_queries": [s.order for s in result.sub_queries],
        },
    )

    return state


# from src.agent.llm.registry import get_llm

# llm = get_llm("openai/gpt-oss-20b")
# state = {
#     "construct": {
#         "constructed_query": "students who comes always late and teachers too."
#     },
#     "domain_context": "retail / CRM",
# }
# result = query_decomposer(llm=llm, state=state)
# decomposed = result["decomposed"]
# print(result)
