# runner.py
import json
import time
import traceback
from .generator import (
    generate_description,
    get_related_tables_strict,
    is_existing_table_valid,
)

from .system import load_existing_results, make_table_key


def generate_all(
    schema_file,
    output_file,
):
    with open(schema_file, "r", encoding="utf-8") as f:
        schema_data = json.load(f)

    # 🔁 Load previous progress
    results = load_existing_results(output_file)

    # Since there's only ONE database, pick it once
    database_name = schema_data[0]["database_name"]

    result_index = {
        make_table_key(r["database_name"], r["table_name"]): idx
        for idx, r in enumerate(results)
    }

    total_tables = len(schema_data)

    print(f"📊 Total tables       : {total_tables}")
    print(f"📊 Already processed  : {len(result_index)}")

    for table in schema_data:
        key = make_table_key(database_name, table["table_name"])

        if key in result_index and is_existing_table_valid(results[result_index[key]]):
            print(f"  ✓ Skipping valid {key}")
            continue

        print(f"  → Generating {key} [{len(result_index)}/{total_tables}]")

        try:
            related_tables = get_related_tables_strict(table, schema_data)

            result = generate_description(
                database_name=database_name,
                all_tables=related_tables,
                target_table=table,
            )

            # Ensure required identifiers exist
            result["database_name"] = database_name
            result["schema_name"] = table.get("schema_name")
            result["table_name"] = table["table_name"]

            # 🔗 Merge sample_values back from original schema
            original_columns = {
                col["name"]: col.get("sample_values", [])
                for col in table.get("columns", [])
            }

            for col in result.get("columns", []):
                if col["name"] in original_columns:
                    col["sample_values"] = original_columns[col["name"]]

            if key in result_index:
                idx = result_index[key]
                results[idx] = result
                print(f"  🔁 Replaced at index {idx}")
            else:
                result_index[key] = len(results)
                results.append(result)
                print(f"  ➕ Added at index {result_index[key]}")

            # 💾 Save after each table
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)

            time.sleep(0.3)

        except Exception as e:
            print(f"❌ Error on {key}: {e}")
            print("⏸ Progress saved. You can safely rerun.")
            print(f"📊 Progress: {len(result_index)}/{total_tables} completed")
            print("\n🔍 FULL TRACEBACK (exact failure location):")
            traceback.print_exc()
            return

    print("\n🎉 ALL TABLES COMPLETED")
