import json
from .system import estimate_tokens

MAX_TOKENS = 2000


def build_prompt(database_name, all_tables, target_table):
    return f"""
You are a high-accuracy schema documentation generator.

You ALWAYS return STRICT VALID JSON.
NO markdown. NO explanations. JSON only.

Use the format demonstrated in the FEW-SHOTS.
Preserve type, constraint, and relation EXACTLY as given.

IMPORTANT:
- Output ONLY the REQUIRED OUTPUT JSON
- Do NOT include code, examples, or explanations
- Do NOT explain how to generate JSON
- Return EXACTLY one valid JSON object.
- Generate ONLY semantic descriptions
- Do NOT invent or modify schema
- Sample values are HINTS, not authoritative truth
- Do NOT copy sample values into the output
- Do NOT add explanations, notes, markdown, code fences, or text of any kind.
- The first character of your response MUST be '{' "and the last character MUST be '}'.

### DATABASE CONTEXT:
Database Name: {database_name}

All Tables in This Database:
{json.dumps(all_tables, indent=2)}

### TARGET TABLE TO DESCRIBE:
{json.dumps(target_table, indent=2)}

### REQUIRED OUTPUT (STRICT JSON ONLY):
{{
  "table_name": "<same as input>",
  "table_description": "<clear semantic meaning>",
  "columns": [
    {{
      "name": "<same as input>",
      "type": "<same as input>",
      "constraint": "<same as input>",
      "relation": "<same as input>",
      "description": "<semantic meaning only>"
    }}
  ]
}}
"""


def strip_sample_values(table: dict) -> dict:
    table = json.loads(json.dumps(table))  # deep copy
    for col in table.get("columns", []):
        col.pop("sample_values", None)
    return table


def build_context_with_budget(
    database_name: str,
    target_table: dict,
    related_tables: list,
    max_tokens: int = 2000,
):
    """
    Strategy:
    1. Always keep target_table
    2. Remove sample_values first
    3. Then drop related tables one by one
    """

    # -------------------------------
    # 🛑 HARD TYPE NORMALIZATION STEP
    # -------------------------------
    normalized_tables = []

    for t in related_tables:
        if isinstance(t, dict):
            normalized_tables.append(t)
        else:
            raise TypeError(f"Expected table dict, got {type(t)}: {t}")

    # -------------------------------
    # Separate roles explicitly
    # -------------------------------
    target_name = target_table["table_name"]

    optional_tables = [t for t in normalized_tables if t["table_name"] != target_name]

    # -------------------------------
    # Attempt 1: full context
    # -------------------------------
    context_tables = [target_table] + optional_tables
    prompt = build_prompt(database_name, context_tables, target_table)

    if estimate_tokens(prompt) <= max_tokens:
        return prompt

    # -------------------------------
    # Attempt 2: remove samples
    # -------------------------------
    stripped_target = strip_sample_values(target_table)
    stripped_optional = [strip_sample_values(t) for t in optional_tables]

    context_tables = [stripped_target] + stripped_optional
    prompt = build_prompt(database_name, context_tables, stripped_target)

    if estimate_tokens(prompt) <= max_tokens:
        return prompt

    # -------------------------------
    # Attempt 3: drop related tables
    # -------------------------------
    while stripped_optional:
        stripped_optional.pop()
        context_tables = [stripped_target] + stripped_optional
        prompt = build_prompt(database_name, context_tables, stripped_target)

        if estimate_tokens(prompt) <= max_tokens:
            return prompt

    # -------------------------------
    # Final fallback: target only
    # -------------------------------
    return build_prompt(database_name, [stripped_target], stripped_target)
