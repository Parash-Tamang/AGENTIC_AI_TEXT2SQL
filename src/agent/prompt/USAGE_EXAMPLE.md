# Prompt Pipeline Usage Example

## Quick Start

```python
from src.agent.prompt import initialize_pipeline_sync

# Initialize pipeline with your API endpoint and connection ID
pipeline = initialize_pipeline_sync(
    base_url="http://192.168.40.121:5197",
    connection_id="9DD2E9F0-4293-4E55-8E88-6FE881E5FC89"
)

# Get prompts
sql_prompt = pipeline.prompt_client.get_system_prompt("sql_generator")
intent_prompt = pipeline.prompt_client.get_system_prompt("intent_classifier")
```

## API Endpoint

The pipeline makes a POST request to:
```
POST http://192.168.40.121:5197/api/agent/V1/prompt-engine/Get-DB-Functions
```

With payload:
```json
{
  "connectionId": "9DD2E9F0-4293-4E55-8E88-6FE881E5FC89"
}
```

Expected response:
```json
{
  "success": true,
  "connectionId": "9DD2E9F0-4293-4E55-8E88-6FE881E5FC89",
  "database": "AdventureWorksLT2019",
  "functions": [
    {
      "functionId": "1",
      "functionName": "sql_generator",
      "systemPrompt": "You are a SQL generation expert..."
    },
    {
      "functionId": "2",
      "functionName": "intent_classifier",
      "systemPrompt": "You are an intent classifier..."
    }
  ]
}
```

## In Your Chat Controller

```python
from src.agent.prompt import initialize_pipeline_sync

@router.post("/", response_model=ApiResult)
async def handle_chat(request: ChatRequest) -> ApiResult:
    try:
        # Initialize pipeline once
        pipeline = initialize_pipeline_sync(
            base_url=os.getenv("PROMPT_API_URL", "http://192.168.40.121:5197"),
            connection_id=os.getenv("CONNECTION_ID", "9DD2E9F0-4293-4E55-8E88-6FE881E5FC89")
        )
        
        # Pass to chat pipeline
        final_state = await run_chat_pipeline(
            user_query=request.query,
            history=[msg.model_dump() for msg in request.history],
            connection=request.connection_string.model_dump(),
            model_name=request.model,
            prompt_client=pipeline.prompt_client  # Pass here
        )
        
        # ... rest of handler
```

## Available Prompt Functions

These map to the `functionName` field in the API response:

- `intent_classifier` - Classify user intent
- `decomposition` - Decompose complex queries
- `sql_generator` - Generate SQL from intent
- `schema_seed_filter` - Filter schema for context
- `schema_sufficiency` - Check schema sufficiency
- `sql_validator` - Validate generated SQL
- `sql_results_validator` - Validate SQL results
- `views_grader` - Grade view quality
- `views_suggestion` - Suggest views
- `generate_response` - Generate user-facing response
- `query_refiner` - Refine user queries
