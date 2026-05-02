from .prompt import build_context_with_budget
from .system import build_system_message
from agent_root.app.src.core.llm.registry import get_llm
from agent_root.app.src.agent.llm_utils import generate_with_estimate
from .json_parser import fix_json_with_llm


def generate_description(database_name, all_tables, target_table):
    prompt = build_context_with_budget(
        database_name=database_name,
        related_tables=all_tables,
        target_table=target_table,
    )
    system_message = build_system_message()
    # print("Prompt tokens:", estimate_tokens(prompt))
    # print("System tokens:", estimate_tokens(system_message))
    # print("Total tokens:", estimate_tokens(prompt + system_message))

    llm = get_llm()
    output, token_info = generate_with_estimate(
        llm,
        system_prompt=system_message,
        user_prompt=prompt,
        step_name="generate_table_description",
    )
    print(f"🔎 generate_description token info: {token_info}")

    try:
        return fix_json_with_llm(output)  # parse_llm_json(output)

    except Exception as e:
        print("⚠️ Failed JSON for table:", target_table["table_name"])
        print("Reason:", e)
        print("Raw output:\n", output)

        return {
            "table_name": target_table["table_name"],
            "table_description": "DESCRIPTION_FAILED",
            "columns": [
                {
                    "name": col,
                    "type": meta["type"],
                    "constraint": meta["constraint"],
                    "relation": meta["relation"],
                    "description": "DESCRIPTION_FAILED",
                }
                for col, meta in target_table["columns"].items()
            ],
        }


def get_related_tables_strict(target_table, all_tables):
    related = {}

    target_name = target_table.get("table_name")
    if not target_name:
        raise ValueError("Target table has no table_name")

    # Always include the target table itself
    related[target_name] = target_table

    # Build lookup index for tables
    table_index = {t.get("table_name"): t for t in all_tables}

    for col in target_table.get("columns", []):
        relation = col.get("relation")

        # ✅ No relation is perfectly valid
        if not relation:
            continue

        # Expected format: TableName.ColumnName
        ref_table = relation.split(".", 1)[0]

        if ref_table not in table_index:
            raise ValueError(
                f"Foreign key reference not found: "
                f"{target_name}.{col.get('name')} → {relation}"
            )

        related[ref_table] = table_index[ref_table]

    return list(related.values())


def is_existing_table_valid(table):
    if (
        table["table_description"] == "DESCRIPTION_FAILED"
        or table["table_description"] == ""
    ):
        return False
    for column in table["columns"]:
        if (
            column["description"] == "DESCRIPTION_FAILED "
            or column["description"] == ""
        ):
            return False
    return True
