import json


def safe_sample(v):
    if isinstance(v, bytes):
        return "<binary>"
    return str(v)


def extract_metadata(schema_data, collection):
    """
    Converts enriched schema into:
    - semantic documents (for embeddings)
    - structured metadata (for reasoning)
    Stores them into Chroma.
    """

    ids, docs, metadatas = [], [], []

    for table in schema_data:
        table_name = table["table_name"]
        schema_name = table["schema_name"]
        table_desc = table.get("table_description") or ""
        db_name = table["database_name"]

        # ---------- SEMANTIC DOCUMENT ----------
        semantic_lines = [
            f"Database: {db_name}",
            f"Schema: {schema_name}",
            f"Table: {table_name}",
            f"Description: {table_desc}",
            "",
            "Columns:",
        ]

        for col in table["columns"]:
            semantic_lines.append(f"- {col['name']}: {col.get('description', '')}")

        combined_text = "\n".join(semantic_lines)

        doc_id = f"{db_name}.{schema_name}.{table_name}"

        ids.append(doc_id)
        docs.append(combined_text)

        # ---------- STRUCTURAL METADATA ----------
        column_metadata = {}

        for col in table["columns"]:
            column_metadata[col["name"]] = {
                "type": col.get("type"),
                "constraint": col.get("constraint"),
                "relation": col.get("relation"),
                "sample_values": [safe_sample(v) for v in col.get("sample_values", [])],
            }

        metadatas.append(
            {
                "database": db_name,
                "schema": schema_name,
                "table": table_name,
                "table_role": table.get("table_role", "entity"),
                "num_columns": len(table["columns"]),
                "columns_json": json.dumps(column_metadata),
            }
        )

    collection.add(ids=ids, documents=docs, metadatas=metadatas)

    return len(ids)
