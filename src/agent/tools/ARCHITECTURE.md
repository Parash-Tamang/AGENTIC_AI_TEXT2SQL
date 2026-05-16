"""
TOOL ABSTRACTION ARCHITECTURE
==============================

Problem:
  Exposing database credentials (db_type, server, username, password) to the LLM
  is a security risk. The LLM doesn't need to know these details.

Solution:
  - Separate concerns: credentials ↔ tool logic
  - LLM only sees the essential parameters (SQL, table names, etc.)
  - Connection config is injected at runtime, never exposed to LLM

Architecture:
  ┌─────────────────────────────────────────────────────────────────┐
  │                         LLM (Claude)                            │
  │                                                                 │
  │  Sees TOOLS without credentials                               │
  │  - generate_schema()  → {}                                     │
  │  - execute_query(sql) → {"sql": "SELECT ..."}                 │
  │                                                                 │
  └────────────────────────┬──────────────────────────────────────┘
                           │ tool_use block
                           ↓
  ┌─────────────────────────────────────────────────────────────────┐
  │  src/agent/tools/executor.py                                    │
  │                                                                 │
  │  dispatch(tool_name, tool_inputs)                              │
  │    ↓                                                             │
  │    1. Look up handler function                                  │
  │    2. Inject connection config from config.py                  │
  │    3. Call underlying database function                        │
  │    4. Return result JSON                                       │
  │                                                                 │
  └────────────────────────┬──────────────────────────────────────┘
                           │
                           ↓
  ┌─────────────────────────────────────────────────────────────────┐
  │  src/agent/tools/config.py (Runtime)                           │
  │                                                                 │
  │  set_connection_config(db_type, server, database, ...)         │
  │  get_connection_config() → ConnectionConfig                    │
  │                                                                 │
  │  Connection details stored once, used by ALL tool calls       │
  │  (Set on server startup, never exposed to LLM)                │
  │                                                                 │
  └──────────────────────────────────────────────────────────────────┘
                           ↓
  ┌─────────────────────────────────────────────────────────────────┐
  │  src/database/executor.py (Database Layer)                     │
  │                                                                 │
  │  generate_schema(db_type, server, database, ...)              │
  │  execute_query(sql, db_type, server, database, ...)           │
  │  generate_views(...)                                           │
  │  execute_view(...)                                             │
  │  bfs_schema_with_joins(...)                                    │
  │                                                                 │
  │  These functions now receive ALL params injected by executor.py│
  │                                                                 │
  └──────────────────────────────────────────────────────────────────┘


Files Structure:
  src/agent/tools/
    ├── __init__.py          # Public API exports
    ├── config.py            # ConnectionConfig + setter/getter
    ├── definitions.py       # Simplified TOOLS for LLM (no credentials)
    ├── executor.py          # Dispatch logic + connection injection
    ├── cot.py              # Chain-of-thought reasoning
    └── example_usage.py     # How to use this abstraction


Usage Flow:
  1. Server startup:
       from src.agent.tools import set_connection_config
       set_connection_config(
           db_type="mssql",
           server="localhost",
           database="MyDB",
           username="user",
           password="pass"
       )

  2. Agent loop:
       from src.agent.tools import TOOLS, dispatch_to_tool_result
       
       # Send TOOLS to Claude (no credentials!)
       response = claude.messages.create(..., tools=TOOLS)
       
       # For each tool_use in response:
       for block in response.content:
           if block.type == "tool_use":
               result = dispatch_to_tool_result(block)
               # Append result to messages and continue...

  3. Inside executor:
       def _handle_execute_query(inputs):
           conn = get_connection_config()  # Get injected config
           return _execute_query(
               sql=inputs["sql"],
               db_type=conn.db_type,  # ← Injected
               server=conn.server,    # ← Injected
               ...
           )


Key Benefits:
  ✅ LLM never sees credentials
  ✅ Credentials centralized (one place to update)
  ✅ Easier testing (can reset config between tests)
  ✅ Cleaner tool definitions
  ✅ Secure by design
  ✅ Simple API (just set_connection_config + dispatch)


Testing Example:
  from src.agent.tools import set_connection_config, reset_connection_config, dispatch
  
  def test_execute_query():
      set_connection_config(
          db_type="mssql",
          server="localhost",
          database="TestDB",
          username="test",
          password="test"
      )
      
      result = dispatch("execute_query", {"sql": "SELECT 1"})
      assert json.loads(result).get("success")
      
      reset_connection_config()  # Clean up


Security Considerations:
  1. Set connection config on server startup (before accepting LLM input)
  2. Never include credentials in TOOLS schema
  3. Connection config is process-scoped (thread-safe for single-threaded server)
  4. For production, use environment variables:
       import os
       set_connection_config(
           db_type=os.getenv("DB_TYPE"),
           server=os.getenv("DB_SERVER"),
           database=os.getenv("DB_DATABASE"),
           username=os.getenv("DB_USER"),
           password=os.getenv("DB_PASSWORD"),
       )
"""
