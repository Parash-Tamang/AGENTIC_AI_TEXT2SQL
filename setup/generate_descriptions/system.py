# system.py
import os
from .few_shots import FEW_SHOTS_1, FEW_SHOTS_2, FEW_SHOTS_3
import json

MAX_CTX = 4096
SAFE_LIMIT = 4000


def load_existing_results(output_file):
    if os.path.exists(output_file):
        with open(output_file, "r", encoding="utf-8") as f:
            schema_data = json.load(f)
        schema_data = [
            i
            for i in schema_data
            if isinstance(i, dict) and "table_name" in i and i["table_name"]
        ]
        return schema_data
    return []


def make_table_key(db_name, table_name):
    return f"{db_name}.{table_name}"


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def build_system_message() -> str:
    shots = [FEW_SHOTS_1, FEW_SHOTS_2, FEW_SHOTS_3]
    system = ""
    for idx, shot in enumerate(shots):
        if estimate_tokens(shot) < SAFE_LIMIT:
            system += "\n" + shot
            # print(f"Few-shot {idx + 1} added")
        else:
            break

    return system.strip()


def get_related_tables_strict(target_table, all_tables):
    related = {}
    target_name = target_table.get("table")

    if not target_name:
        raise ValueError("Target table has no name")

    related[target_name] = target_table

    # Build lookup index
    table_index = {t.get("table"): t for t in all_tables}

    for col_name, col in target_table.get("columns", {}).items():
        relation = col.get("relation")
        if not relation:
            continue  # ✅ no FK is perfectly fine

        ref_table = relation.split(".", 1)[0]

        if ref_table not in table_index:
            raise ValueError(
                f"Foreign key reference not found: "
                f"{target_name}.{col_name} → {relation}"
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
