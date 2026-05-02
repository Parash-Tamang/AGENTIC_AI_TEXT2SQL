from .fetch_samples_data import fetch_column_samples


def enrich_schema(schema, conn):

    enriched = []

    for table_key, table_data in schema.items():
        # table_key = AdventureWorksLT2019.SalesLT.Address
        database_name = table_data["database"]
        schema_name = table_data["schema"]
        table_name = table_data["table"]

        table_obj = {
            "database_name": database_name,
            "schema_name": schema_name,
            "table_name": table_name,
            "table_description": None,
            "columns": [],
        }

        for col_name, col in table_data["columns"].items():
            samples = fetch_column_samples(
                conn,
                database_name=database_name,
                schema_name=schema_name,
                table_name=table_name,
                column_name=col_name,
                sql_type=col["type"],
            )

            if col["key"] == "primary":
                constraint = "Primary Key"
            elif col["key"] == "foreign":
                constraint = "Foreign Key"
            elif col["nullable"]:
                constraint = "nullable"
            else:
                constraint = "not null"

            column_obj = {
                "name": col_name,
                "type": col["type"],
                "constraint": constraint,
                "relation": (
                    f"{col['references']['table']}.{col['references']['column']}"
                    if col["references"]
                    else None
                ),
                "description": None,
                "sample_values": samples,
            }

            table_obj["columns"].append(column_obj)

        enriched.append(table_obj)

    return enriched
