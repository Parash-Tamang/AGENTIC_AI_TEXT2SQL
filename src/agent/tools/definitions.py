"""
Tool definitions for Groq LLM.
Pure data — no imports from this package.
"""

TOOLS = [
    {
        "name": "execute_query",
        "description": (
            "Execute a SQL query string against the database and return rows. "
            "Use for SELECT statements after schema context is built. "
            "Always check 'success' before reading 'rows'. "
            "On failure, pass 'error' back to the LLM for self-correction. "
            "Default row cap is 100 — raise max_rows explicitly if more are needed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Full SQL query string to execute.",
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return.",
                    "default": 100,
                },
                "expected_columns": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Optional list of expected column names for validation.",
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "execute_view",
        "description": (
            "Execute a named database view and return its rows. "
            "Prefer over execute_query when a pre-built view already answers the question. "
            "Avoids SQL generation errors entirely. "
            "Always pass 'schema' to qualify the view name unambiguously."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "view_name": {
                    "type": "string",
                    "description": "Exact name of the view to execute.",
                },
                "schema": {
                    "type": "string",
                    "description": "Schema that owns the view.",
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return.",
                    "default": 100,
                },
                "expected_columns": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Optional list of expected column names for validation.",
                },
            },
            "required": ["view_name", "schema"],
        },
    },
    {
        "name": "fetch_schema",
        "description": (
            "Semantic search for specific table/column metadata from the vector store. "
            "Use for targeted schema discovery by natural language query. "
            "Returns tables that match your search text with full column definitions. "
            "If results are empty, broaden your query terms and try again."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language query about tables/columns. "
                        "e.g., 'customer orders', 'product catalog', 'sales transactions'."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return.",
                    "default": 5,
                },
                "schema_name": {
                    "type": ["string", "null"],
                    "description": "Optional: filter by schema name.",
                },
                "table_name": {
                    "type": ["string", "null"],
                    "description": "Optional: filter by exact table name.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_view",
        "description": (
            "Semantic search for view definitions and metadata from the vector store. "
            "Discover pre-built views that may answer your question directly. "
            "Returns view definitions, columns, and data types."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural language query about views. "
                        "e.g., 'customer summary', 'sales by region'."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return.",
                    "default": 5,
                },
                "schema_name": {
                    "type": ["string", "null"],
                    "description": "Optional: filter by schema name.",
                },
                "view_name": {
                    "type": ["string", "null"],
                    "description": "Optional: filter by exact view name.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "bfs_join",
        "description": (
            "BFS traversal of the schema graph starting from seed tables. "
            "Discovers all related tables and explicit JOIN conditions within max_hops. "
            "Returns token-budgeted schema context ready to inject into SQL generation. "
            "Call after identifying seed tables from fetch_schema, before generating SQL."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "seed_tables": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Starting tables in 'Schema.Table' format. "
                        "e.g., ['Schema.Customer', 'Schema.SalesOrderHeader']."
                    ),
                },
                "max_hops": {
                    "type": "integer",
                    "description": "Maximum relationship hops to traverse.",
                    "default": 2,
                },
                "token_limit": {
                    "type": "integer",
                    "description": "Token budget cap for output context.",
                    "default": 8000,
                },
            },
            "required": ["seed_tables"],
        },
    },
]
