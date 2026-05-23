# API Controller Reference

This document lists all HTTP APIs exposed by the project controllers and shows the request input and response output format for each route.

## Overview

The application exposes three API groups:

- `GET /health` from `src/main.py`
- `POST /chat/` from `src/agent/controller/chat_controller.py`
- `/knowledgebase/*` from `src/knowledgebase/controller/knowledgebase_controller.py`

## Common Response Shapes

### `ApiResult`
Used by the chat endpoint.

```json
{
  "success": true,
  "message": "Processed successfully.",
  "data": {
    "response": "final answer text"
  }
}
```

### `ApiResponse[T]`
Used by knowledgebase endpoints.

```json
{
  "success": true,
  "message": "Operation completed successfully.",
  "data": {}
}
```

## Shared Request Models

### ChatRequest
Used by `POST /chat/`.

```json
{
  "query": "show total sales by region",
  "history": [
    {
      "role": "user",
      "content": "previous question"
    }
  ],
  "connection_string": {
    "db_type": "mssql",
    "server": "(localdb)\\MSSQLLocalDB",
    "database": "AdventureWorksLT2019",
    "username": "sa",
    "password": "1234567890",
    "port": 1143,
    "pool_size": 5,
    "timeout": 30
  },
  "model": "meta-llama/llama-4-scout-17b-16e-instruct"
}
```

### DBConnectionRequest
Used by knowledgebase create, update, and delete operations.

```json
{
  "db_type": "mssql",
  "server": "(localdb)\\MSSQLLocalDB",
  "username": "sa",
  "password": "1234567890",
  "timeout": 30,
  "excluded_schemas": [],
  "excluded_tables": [],
  "excluded_columns": []
}
```

## API List

### 1. Health Check

- Method: `GET`
- Path: `/health`
- Controller: `src/main.py`
- Input: none
- Output type: `ApiResult`

Response example:

```json
{
  "success": true,
  "message": "API is running",
  "data": null
}
```

### 2. Chat Pipeline

- Method: `POST`
- Path: `/chat/`
- Controller: `src/agent/controller/chat_controller.py`
- Input type: `ChatRequest`
- Output type: `ApiResult`

Request example:

```json
{
  "query": "top 10 customers by sales",
  "history": [],
  "connection_string": {
    "db_type": "mssql",
    "server": "(localdb)\\MSSQLLocalDB",
    "database": "AdventureWorksLT2019",
    "username": "sa",
    "password": "1234567890",
    "port": 1143,
    "pool_size": 5,
    "timeout": 30
  },
  "model": "meta-llama/llama-4-scout-17b-16e-instruct"
}
```

Response example:

```json
{
  "success": true,
  "message": "Processed successfully.",
  "data": {
    "response": "Here is the answer based on your data..."
  }
}
```

### 3. List Indexed Databases

- Method: `GET`
- Path: `/knowledgebase/list`
- Controller: `src/knowledgebase/controller/knowledgebase_controller.py`
- Input: none
- Output type: `ApiResponse[ListDatabasesResponse]`

Response example:

```json
{
  "success": true,
  "message": "Databases retrieved successfully",
  "data": {
    "databases": {
      "AdventureWorksLT2019": ["schemas", "views"]
    },
    "total": 1
  }
}
```

### 4. Get Knowledgebase Stats

- Method: `GET`
- Path: `/knowledgebase/{database_name}/stats`
- Input path parameter: `database_name`
- Output type: `ApiResponse[StatsResponse]`

Response example:

```json
{
  "success": true,
  "message": "Stats retrieved successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "schema_collection": {},
    "views_collection": {},
    "total_documents": 0,
    "persist_directory": "..."
  }
}
```

### 5. Create Schemas

- Method: `POST`
- Path: `/knowledgebase/{database_name}/schemas/create`
- Input:
  - path parameter: `database_name`
  - body: `DBConnectionRequest`
- Output type: `ApiResponse[IndexResponse]`
- Status code: `201 Created`

Response example:

```json
{
  "success": true,
  "message": "Schemas created and indexed successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "schema_type": "table",
    "indexed": 42,
    "message": "Generated and indexed 42 table schemas for 'AdventureWorksLT2019'"
  }
}
```

### 6. Create Views

- Method: `POST`
- Path: `/knowledgebase/{database_name}/views/create`
- Input:
  - path parameter: `database_name`
  - body: `DBConnectionRequest`
- Output type: `ApiResponse[IndexResponse]`
- Status code: `201 Created`

Response example:

```json
{
  "success": true,
  "message": "Views created and indexed successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "schema_type": "view",
    "indexed": 12,
    "message": "Generated and indexed 12 views for 'AdventureWorksLT2019'"
  }
}
```

### 7. Update Schemas

- Method: `PUT`
- Path: `/knowledgebase/{database_name}/schemas/update`
- Input:
  - path parameter: `database_name`
  - body: `DBConnectionRequest`
- Output type: `ApiResponse[IndexResponse]`

Response example:

```json
{
  "success": true,
  "message": "Schemas updated successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "schema_type": "table",
    "indexed": 42,
    "message": "Wiped and reindexed 42 table schemas for 'AdventureWorksLT2019'"
  }
}
```

### 8. Update Views

- Method: `PUT`
- Path: `/knowledgebase/{database_name}/views/update`
- Input:
  - path parameter: `database_name`
  - body: `DBConnectionRequest`
- Output type: `ApiResponse[IndexResponse]`

Response example:

```json
{
  "success": true,
  "message": "Views updated successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "schema_type": "view",
    "indexed": 12,
    "message": "Wiped and reindexed 12 views for 'AdventureWorksLT2019'"
  }
}
```

### 9. Delete Schemas

- Method: `DELETE`
- Path: `/knowledgebase/{database_name}/schemas/delete`
- Input path parameter: `database_name`
- Output type: `ApiResponse[DeleteResponse]`

Response example:

```json
{
  "success": true,
  "message": "Schemas deleted successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "deleted": ["schemas", "schema_graph"],
    "message": "schemas removed, graph removed for 'AdventureWorksLT2019'"
  }
}
```

### 10. Delete Views

- Method: `DELETE`
- Path: `/knowledgebase/{database_name}/views/delete`
- Input path parameter: `database_name`
- Output type: `ApiResponse[DeleteResponse]`

Response example:

```json
{
  "success": true,
  "message": "Views deleted successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "deleted": ["views", "schema_graph"],
    "message": "views removed, graph removed for 'AdventureWorksLT2019'"
  }
}
```

### 11. Delete Database Collections

- Method: `DELETE`
- Path: `/knowledgebase/{database_name}/delete`
- Input path parameter: `database_name`
- Output type: `ApiResponse[DeleteResponse]`

Response example:

```json
{
  "success": true,
  "message": "Database deleted successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "deleted": ["schemas", "views", "schema_graph"],
    "message": "schemas removed, views removed, graph removed for 'AdventureWorksLT2019'"
  }
}
```

### 12. Create Schema Graph

- Method: `POST`
- Path: `/knowledgebase/{database_name}/graphs/create`
- Input path parameter: `database_name`
- Output type: `ApiResponse[GraphResponse]`
- Status code: `201 Created`

Response example:

```json
{
  "success": true,
  "message": "Graph created successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "graph_path": ".../AdventureWorksLT2019",
    "message": "Schema graph created for 'AdventureWorksLT2019'"
  }
}
```

### 13. Update Schema Graph

- Method: `PUT`
- Path: `/knowledgebase/{database_name}/graphs/update`
- Input path parameter: `database_name`
- Output type: `ApiResponse[GraphResponse]`

Response example:

```json
{
  "success": true,
  "message": "Graph updated successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "graph_path": ".../AdventureWorksLT2019",
    "message": "Schema graph rebuilt for 'AdventureWorksLT2019'"
  }
}
```

### 14. Delete Schema Graph

- Method: `DELETE`
- Path: `/knowledgebase/{database_name}/graphs/delete`
- Input path parameter: `database_name`
- Output type: `ApiResponse[DeleteResponse]`

Response example:

```json
{
  "success": true,
  "message": "Graph deleted successfully",
  "data": {
    "database_name": "AdventureWorksLT2019",
    "deleted": ["schema_graph"],
    "message": "Schema graph deleted for 'AdventureWorksLT2019'"
  }
}
```

## Notes

- Chat requests require a database connection object in the body.
- Knowledgebase endpoints use a generic `success/message/data` wrapper.
- Error responses are returned as HTTP errors, usually with `detail` in the FastAPI exception layer.
- All route prefixes are included exactly as exposed by the routers.

## Main Request Models

### ConnectionConfig
Used inside `ChatRequest.connection_string`.

```json
{
  "db_type": "mssql",
  "server": "(localdb)\\MSSQLLocalDB",
  "database": "AdventureWorksLT2019",
  "username": "sa",
  "password": "1234567890",
  "port": 1143,
  "pool_size": 5,
  "timeout": 30
}
```

### ChatMessage
Used inside `ChatRequest.history`.

```json
{
  "role": "user",
  "content": "show total sales by month"
}
```

### DBConnectionRequest
Used by knowledgebase controller routes.

```json
{
  "db_type": "mssql",
  "server": "(localdb)\\MSSQLLocalDB",
  "username": "sa",
  "password": "1234567890",
  "timeout": 30,
  "excluded_schemas": [],
  "excluded_tables": [],
  "excluded_columns": []
}
```
