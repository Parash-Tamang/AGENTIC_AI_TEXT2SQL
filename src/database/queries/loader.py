import os


def load_schema_queries(db_type: str = None):
    queries = {}
    base_path = os.path.dirname(__file__)

    # 👉 If specific DB requested
    if db_type:
        file_path = os.path.join(base_path, f"{db_type}.sql")

        if not os.path.exists(file_path):
            raise ValueError(f"No query file found for DB_TYPE: {db_type}")

        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()  # return single query

    # 👉 Else load all
    for file in os.listdir(base_path):
        if file.endswith(".sql"):
            key = file.replace(".sql", "")
            file_path = os.path.join(base_path, file)

            with open(file_path, "r", encoding="utf-8") as f:
                queries[key] = f.read()

    return queries
