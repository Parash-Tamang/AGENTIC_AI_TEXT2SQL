def fetch_column_samples(
    conn,
    schema_name,
    database_name,
    table_name,
    column_name,
    sql_type: str,
    limit: int = 3,
):
    """
    Fetch small, semantically useful sample values for a column.
    """

    # ❌ Skip non-semantic SQL types early
    NON_SEMANTIC_TYPES = {
        "varbinary",
        "image",
        "binary",
        "blob",
        "xml",
        "text",
        "ntext",
    }

    if any(t in sql_type.lower() for t in NON_SEMANTIC_TYPES):
        return []

    query = f"""
    SELECT TOP ({limit})
        [{column_name}]
    FROM [{schema_name}].[{table_name}]
    WHERE [{column_name}] IS NOT NULL
    """

    cursor = conn.cursor()
    cursor.execute(f"USE {database_name}")
    cursor.execute(query)

    samples = []

    for row in cursor.fetchall():
        val = row[0]

        # ❌ Skip raw bytes
        if isinstance(val, (bytes, bytearray)):
            continue

        # Convert safely
        val = str(val)

        # ❌ Skip huge strings
        if len(val) > 50:
            val = val[:50] + "…"

        samples.append(val)

    return samples
