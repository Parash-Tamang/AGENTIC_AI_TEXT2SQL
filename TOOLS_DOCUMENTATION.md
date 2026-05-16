# RAG System Tools Documentation

Complete reference for core tools used in the Retrieval-Augmented Generation (RAG) system for SQL query generation.

---

## Tools

### 1. generate_schema

**Module**: `src/database/executor.py`

**Purpose**: Generate and return the complete database schema including tables, columns, data types, primary keys, and foreign key relationships from SQL Server.

**Function Signature**:
```python
def generate_schema(
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
    exclusions: Optional[ExclusionConfig] = None,
) -> dict
```

#### Input

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `db_type` | `str` | Yes | Database type ("mssql", "postgres", etc.) |
| `server` | `str` | Yes | Database server hostname/IP |
| `database` | `str` | Yes | Database name (e.g., "AdventureWorksLT2019") |
| `username` | `str` | Yes | Database user |
| `password` | `str` | Yes | Database password |
| `pool_size` | `int` | No | Connection pool size (default: 5) |
| `timeout` | `int` | No | Query timeout in seconds (default: 30) |
| `port` | `int` | No | Database port (optional) |
| `exclusions` | `ExclusionConfig` | No | Optional exclusion rules for tables/schemas |

#### Output

```json
{
  "database.schema.table_name": {
    "database": "AdventureWorksLT2019",
    "schema": "SalesLT",
    "table": "Customer",
    "columns": {
      "CustomerID": {
        "type": "INT",
        "nullable": false,
        "key": "primary",
        "references": null
      },
      "CompanyName": {
        "type": "NVARCHAR",
        "nullable": false,
        "key": null,
        "references": null
      },
      "SalesPersonID": {
        "type": "INT",
        "nullable": true,
        "key": "foreign",
        "references": {
          "table": "SalesPerson",
          "column": "SalesPersonID"
        }
      }
    }
  }
}
```

#### Key Features
- Extracts all tables, columns, data types
- Identifies primary keys and foreign keys
- Resolves foreign key references
- Returns nullable constraints
- Organized by `database.schema.table` hierarchy
- Supports optional exclusion rules

#### Errors
- Connection failures
- Invalid database name
- Permission issues on system tables

---

### 2. generate_views

**Module**: `src/database/executor.py`

**Purpose**: Fetch and return metadata for all database views including view definitions, columns, and data types.

**Function Signature**:
```python
def generate_views(
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
) -> list[ViewSchema]
```

#### Input

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `db_type` | `str` | Yes | Database type ("mssql", "postgres", etc.) |
| `server` | `str` | Yes | Database server hostname/IP |
| `database` | `str` | Yes | Database name (e.g., "AdventureWorksLT2019") |
| `username` | `str` | Yes | Database user |
| `password` | `str` | Yes | Database password |
| `pool_size` | `int` | No | Connection pool size (default: 5) |
| `timeout` | `int` | No | Query timeout in seconds (default: 30) |
| `port` | `int` | No | Database port (optional) |

#### Output

```json
[
  {
    "database_name": "AdventureWorksLT2019",
    "schema_name": "SalesLT",
    "view_name": "vGetAllCategories",
    "view_description": "View displaying all product categories",
    "view_definition": "CREATE VIEW vGetAllCategories AS SELECT ...",
    "columns": [
      {
        "name": "CategoryID",
        "type": "INT",
        "description": "Primary key for the category"
      },
      {
        "name": "ParentCategoryID",
        "type": "INT",
        "description": "Foreign key to parent category"
      },
      {
        "name": "Name",
        "type": "NVARCHAR(50)",
        "description": "Category name"
      }
    ]
  },
  {
    "database_name": "AdventureWorksLT2019",
    "schema_name": "SalesLT",
    "view_name": "vProductAndDescription",
    "view_description": "Product information with descriptions",
    "view_definition": "CREATE VIEW vProductAndDescription AS SELECT ...",
    "columns": [
      {
        "name": "ProductID",
        "type": "INT",
        "description": "Product identifier"
      },
      {
        "name": "Name",
        "type": "NVARCHAR(50)",
        "description": "Product name"
      },
      {
        "name": "Description",
        "type": "NVARCHAR(MAX)",
        "description": "Product description"
      }
    ]
  }
]
```

#### Key Features
- Extracts all views from the database
- Includes view definitions and SQL
- Resolves column types and descriptions
- Organized by database, schema, and view name
- Skips system schemas (sys, information_schema, etc.)
- Returns structured ViewSchema objects

#### Errors
- Connection failures
- Invalid database name
- Permission issues on system catalogs

---
### 3. fetch_schema_metadata

**Module**: `src/knowledgebase/stores/vector_store.py`

**Purpose**: Fetch and retrieve cached schema metadata for specific tables, columns, or schemas from the vector store with optional filtering by schema name or table name.

**Function Signature**:
```python
def query_schemas(
    embedding: list[float],
    database_name: str,
    top_k: Optional[int] = None,
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
) -> list[dict[str, Any]]
```

#### Input

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `embedding` | `list[float]` | Yes | Query embedding vector (from semantic search) |
| `database_name` | `str` | Yes | Database name (e.g., "AdventureWorksLT2019") |
| `top_k` | `int` | No | Number of results to return (default: from settings) |
| `schema_name` | `str` | No | Filter by schema name (e.g., "SalesLT") |
| `table_name` | `str` | No | Filter by specific table name |

#### Output

```json
[
  {
    "document": "Table: SalesLT.Customer\nColumns: CustomerID (INT, PK), CompanyName (NVARCHAR), EmailAddress (NVARCHAR), Phone (NVARCHAR), CreatedDate (DATETIME2)",
    "metadata": {
      "database_name": "AdventureWorksLT2019",
      "schema_name": "SalesLT",
      "table_name": "Customer",
      "type": "table_schema"
    },
    "distance": 0.125
  },
  {
    "document": "Table: SalesLT.SalesOrderHeader\nColumns: SalesOrderID (INT, PK), CustomerID (INT, FK), OrderDate (DATETIME2), TotalDue (MONEY)",
    "metadata": {
      "database_name": "AdventureWorksLT2019",
      "schema_name": "SalesLT",
      "table_name": "SalesOrderHeader",
      "type": "table_schema"
    },
    "distance": 0.145
  }
]
```

#### Key Features
- Retrieves cached schema documents from vector store
- Semantic similarity-based search
- Optional filtering by schema or table name
- Ranked by distance (similarity)
- Much faster than `generate_schema` for targeted queries
- Uses ONNX embeddings for efficient CPU-based retrieval

#### Usage Context
- Used in Stage 4 of RAG pipeline for schema retrieval
- Complements `generate_schema` for faster lookup
- Supports incremental context building

#### Errors
- Missing database_name
- Empty vector store
- No matching results after filtering

---
### 4. fetch_view_metadata

**Module**: `src/knowledgebase/stores/vector_store.py`

**Purpose**: Fetch and retrieve cached view metadata from the vector store with semantic search and optional filtering by schema name or view name.

**Function Signature**:
```python
def query_views(
    embedding: list[float],
    database_name: str,
    top_k: Optional[int] = None,
    schema_name: Optional[str] = None,
    view_name: Optional[str] = None,
) -> list[dict[str, Any]]
```

#### Input

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `embedding` | `list[float]` | Yes | Query embedding vector (from semantic search) |
| `database_name` | `str` | Yes | Database name (e.g., "AdventureWorksLT2019") |
| `top_k` | `int` | No | Number of results to return (default: from settings) |
| `schema_name` | `str` | No | Filter by schema name (e.g., "SalesLT") |
| `view_name` | `str` | No | Filter by specific view name |

#### Output

```json
[
  {
    "document": "View: SalesLT.vGetAllCategories\nColumns: CategoryID (INT), ParentCategoryID (INT), Name (NVARCHAR)\nDescription: View displaying all product categories with hierarchy",
    "metadata": {
      "database_name": "AdventureWorksLT2019",
      "schema_name": "SalesLT",
      "view_name": "vGetAllCategories",
      "type": "view"
    },
    "distance": 0.087
  },
  {
    "document": "View: SalesLT.vProductAndDescription\nColumns: ProductID (INT), Name (NVARCHAR), Description (NVARCHAR)\nDescription: Product information with descriptions and category",
    "metadata": {
      "database_name": "AdventureWorksLT2019",
      "schema_name": "SalesLT",
      "view_name": "vProductAndDescription",
      "type": "view"
    },
    "distance": 0.102
  }
]
```

#### Key Features
- Retrieves cached view documents from vector store
- Semantic similarity-based search
- Optional filtering by schema or view name
- Ranked by distance (similarity)
- Complements `generate_views` for faster lookup
- Includes view definitions and column information
- Uses ONNX embeddings for efficient retrieval

#### Usage Context
- Used in RAG pipeline for targeted view discovery
- Faster than `generate_views` for specific view lookups
- Supports filtering by schema

#### Errors
- Missing database_name
- Empty views collection
- No matching results after filtering

---
### 5. execute_query

**Module**: `src/database/executor.py`

**Purpose**: Execute SQL queries against the database and return results with proper error handling and row limiting.

**Function Signature**:
```python
def execute_query(
    sql: str,
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
    max_rows: int = 100,
    expected_columns: Optional[list[str]] = None
) -> dict
```

#### Input

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `sql` | `str` | Yes | SQL query to execute |
| `db_type` | `str` | Yes | Database type ("mssql", "postgres", etc.) |
| `server` | `str` | Yes | Database server hostname/IP |
| `database` | `str` | Yes | Database name |
| `username` | `str` | Yes | Database user |
| `password` | `str` | Yes | Database password |
| `pool_size` | `int` | No | Connection pool size (default: 5) |
| `timeout` | `int` | No | Query timeout in seconds (default: 30) |
| `port` | `int` | No | Database port (optional) |
| `max_rows` | `int` | No | Maximum rows to return (default: 100) |
| `expected_columns` | `list[str]` | No | Expected column names for validation |

#### Output

```json
{
  "success": true,
  "rows": [
    {
      "CustomerID": 1,
      "CompanyName": "Acme Corp",
      "TotalSales": 50000.00
    },
    {
      "CustomerID": 2,
      "CompanyName": "Tech Ltd",
      "TotalSales": 45000.00
    }
  ],
  "row_count": 2,
  "columns": ["CustomerID", "CompanyName", "TotalSales"],
  "execution_time_ms": 245.5,
  "error": null
}
```

#### Key Features
- Executes parameterized queries
- Row limiting (max_rows)
- Connection pooling
- Configurable timeout
- Result validation
- Error handling with messages

#### Errors
```json
{
  "success": false,
  "rows": [],
  "row_count": 0,
  "columns": [],
  "execution_time_ms": 0,
  "error": "Syntax error in SQL query"
}
```

---

### 6. execute_view

**Module**: `src/database/executor.py`

**Purpose**: Execute a database view and return results with proper error handling and row limiting.

**Function Signature**:
```python
def execute_view(
    view_name: str,
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
    schema: Optional[str] = None,
    max_rows: int = 100,
    expected_columns=None,
) -> dict
```

#### Input

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `view_name` | `str` | Yes | Name of the view to execute |
| `db_type` | `str` | Yes | Database type ("mssql", "postgres", etc.) |
| `server` | `str` | Yes | Database server hostname/IP |
| `database` | `str` | Yes | Database name |
| `username` | `str` | Yes | Database user |
| `password` | `str` | Yes | Database password |
| `pool_size` | `int` | No | Connection pool size (default: 5) |
| `timeout` | `int` | No | Query timeout in seconds (default: 30) |
| `port` | `int` | No | Database port (optional) |
| `schema` | `str` | No | Schema name for the view (e.g., "SalesLT") |
| `max_rows` | `int` | No | Maximum rows to return (default: 100) |
| `expected_columns` | `list[str]` | No | Expected column names for validation |

#### Output

```json
{
  "success": true,
  "rows": [
    {
      "CustomerID": 1,
      "CompanyName": "Acme Corp",
      "TotalSales": 50000.00
    },
    {
      "CustomerID": 2,
      "CompanyName": "Tech Ltd",
      "TotalSales": 45000.00
    }
  ],
  "row_count": 2,
  "columns": ["CustomerID", "CompanyName", "TotalSales"],
  "execution_time_ms": 245.5,
  "error": null
}
```

#### Key Features
- Executes named database views
- Row limiting (max_rows)
- Connection pooling
- Configurable timeout
- Result validation
- Error handling with messages
- Optional schema qualification

#### Errors
```json
{
  "success": false,
  "rows": [],
  "row_count": 0,
  "columns": [],
  "execution_time_ms": 0,
  "error": "View does not exist"
}
```

---

### 7. bfs_schema_with_joins

**Module**: `src/knowledgebase/graph/search_graph.py`

**Purpose**: Breadth-First Search (BFS) traversal of database schema graph to discover related tables and join paths starting from seed tables.

**Function Signature**:
```python
def bfs_schema_with_joins(
    graph: nx.DiGraph,
    seed_tables: list[str],
    max_hops: int = 2,
    token_limit: int = 8000
) -> dict
```

#### Input

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `graph` | `nx.DiGraph` | Yes | NetworkX directed graph of schema (nodes=tables/columns, edges=relationships) |
| `seed_tables` | `list[str]` | Yes | Starting table names (e.g., ["SalesLT.Customer", "SalesLT.SalesOrderHeader"]) |
| `max_hops` | `int` | No | Maximum relationship hops to traverse (default: 2) |
| `token_limit` | `int` | No | Token budget for context (default: 8000) |

#### Output

```json
{
  "tables": [
    "SalesLT.Customer",
    "SalesLT.SalesOrderHeader",
    "SalesLT.SalesOrderDetail",
    "SalesLT.Product"
  ],
  "schema": [
    {
      "table": "SalesLT.Customer",
      "columns": [
        {
          "name": "CustomerID",
          "type": "INT",
          "description": "Primary key"
        },
        {
          "name": "CompanyName",
          "type": "NVARCHAR(128)",
          "description": "Customer company name"
        }
      ],
      "joins": [
        "SalesLT.Customer.CustomerID = SalesLT.SalesOrderHeader.CustomerID"
      ]
    },
    {
      "table": "SalesLT.SalesOrderHeader",
      "columns": [
        {
          "name": "SalesOrderID",
          "type": "INT",
          "description": "Primary key"
        },
        {
          "name": "CustomerID",
          "type": "INT",
          "description": "Foreign key to Customer"
        }
      ],
      "joins": [
        "SalesLT.SalesOrderHeader.SalesOrderID = SalesLT.SalesOrderDetail.SalesOrderID",
        "SalesLT.SalesOrderHeader.CustomerID = SalesLT.Customer.CustomerID"
      ]
    }
  ],
  "joins": [
    "SalesLT.Customer.CustomerID = SalesLT.SalesOrderHeader.CustomerID",
    "SalesLT.SalesOrderHeader.SalesOrderID = SalesLT.SalesOrderDetail.SalesOrderID",
    "SalesLT.SalesOrderDetail.ProductID = SalesLT.Product.ProductID"
  ],
  "token_estimate": 3250
}
```

#### Key Features
- BFS traversal from seed tables
- Configurable hop distance
- Token budget enforcement (truncates at limit)
- Collects schema information for each table
- Builds join path documentation
- Estimates token usage for LLM context

#### Graph Requirements

**Nodes**:
- `type`: "table" or "column"
- `name`: node identifier
- `col_type`: (for columns) SQL data type
- `description`: (for columns) semantic description

**Edges**:
- `type`: "fk" (foreign key) or "column" (table-column)
- `from_col`: source column name
- `to_col`: target column name

#### Errors
- Empty seed_tables
- Invalid node types in graph
- No valid seeds found

---

## Usage Examples

### Example 1: Full RAG Pipeline

```python
# 1. Generate Schema
schema = generate_schema(
    db_type="mssql",
    server="localhost",
    database="AdventureWorksLT2019",
    username="sa",
    password="password"
)

# 2. BFS for Related Tables
context = bfs_schema_with_joins(
    graph=graph_manager.get_graph("AdventureWorksLT2019"),
    seed_tables=["SalesLT.Customer", "SalesLT.SalesOrderHeader"],
    max_hops=2,
    token_limit=8000
)

# 3. Execute Generated Query
results = execute_query(
    sql="SELECT TOP 5 c.CustomerID, c.CompanyName, SUM(soh.TotalDue) FROM SalesLT.Customer c JOIN SalesLT.SalesOrderHeader soh ON c.CustomerID = soh.CustomerID GROUP BY c.CustomerID, c.CompanyName",
    db_type="mssql",
    server="localhost",
    database="AdventureWorksLT2019",
    username="sa",
    password="password",
    max_rows=100
)
```

### Example 2: Schema Discovery

```python
# Get all tables and their relationships
schema = generate_schema(
    db_type="mssql",
    server="localhost",
    database="AdventureWorksLT2019",
    username="sa",
    password="password"
)

for table_key, table_info in schema.items():
    print(f"Table: {table_key}")
    for col_name, col_info in table_info["columns"].items():
        print(f"  - {col_name}: {col_info['type']} (Key: {col_info['key']})")
        if col_info.get('references'):
            print(f"    → References: {col_info['references']['table']}.{col_info['references']['column']}")
```

### Example 3: Execute View

```python
# Execute a view directly
view_results = execute_view(
    view_name="CustomerSalesView",
    schema="SalesLT",
    db_type="mssql",
    server="localhost",
    database="AdventureWorksLT2019",
    username="sa",
    password="password",
    max_rows=50
)

if view_results.get('success'):
    print(f"Retrieved {view_results['row_count']} rows in {view_results['execution_time_ms']}ms")
```

### Example 4: Context Building with Graph

```python
# Start from multiple seed tables and find all related tables within 2 hops
bfs_result = bfs_schema_with_joins(
    graph=graph_manager.get_graph("AdventureWorksLT2019"),
    seed_tables=["SalesLT.Customer", "SalesLT.Product"],
    max_hops=2,
    token_limit=6000
)

# Format for LLM prompt
formatted_schema = format_schema_for_prompt(bfs_result)
print(formatted_schema)
```

---

## Integration with RAG System

These tools are used in the RAG pipeline stages:

- **Stage 1**: Query Refinement → Use `generate_schema` and `generate_views` to understand available tables and views
- **Stage 4**: Schema Retrieval → Use `fetch_schema_metadata` for semantic schema lookup or `generate_schema` for full schema
- **Stage 4**: View Retrieval → Use `fetch_view_metadata` for semantic view discovery
- **Stage 5**: Graph BFS → Use `bfs_schema_with_joins` for context expansion
- **Stage 8**: SQL Generation → Provide schema context to LLM
- **Stage 10**: SQL Execution → Use `execute_query` to run generated SQL
- **Bonus**: Execute views directly with `execute_view` for pre-built queries

---

## Performance Considerations

| Tool | Complexity | Cache Time | Notes |
|------|-----------|-----------|-------|
| `generate_schema` | O(tables × columns) | Long (24h) | Stable metadata, cache aggressively |
| `generate_views` | O(views × columns) | Long (24h) | Stable metadata, cache aggressively |
| `fetch_schema_metadata` | O(log n) | Real-time | Vector search, very fast |
| `fetch_view_metadata` | O(log n) | Real-time | Vector search, very fast |
| `execute_query` | O(result rows) | Per query | Depends on query complexity |
| `execute_view` | O(view rows) | Per view | Depends on underlying view |
| `bfs_schema_with_joins` | O(tables + edges) | Medium (6h) | Graph traversal, predictable |

---

## Error Handling

### Connection Errors
```python
try:
    result = execute_query(sql, ...)
except ConnectionError as e:
    log.error(f"Database connection failed: {e}")
```

### Query Errors
```python
if not result.get('success'):
    error_msg = result.get('error')
    log.error(f"Query execution failed: {error_msg}")
```

### Schema Errors
```python
if not schema:
    log.warning("No schema retrieved - database may be empty")
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | May 2026 | Initial documentation |

