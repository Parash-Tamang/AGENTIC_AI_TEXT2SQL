from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List

from src.api_response import ApiResult
from src.exceptions import AppBaseException
from src.agent.orchestrator.chat import run_chat_pipeline

router = APIRouter(prefix="/chat", tags=["Chat Environment"])


class ChatMessage(BaseModel):
    role: str = Field(
        description="Role of the message sender, e.g., 'user' or 'assistant'"
    )
    content: str = Field(description="The text content of the message")


class ConnectionConfig(BaseModel):
    db_type: str = Field(default="mssql", description="Database engine type")
    server: str = Field(
        default="(localdb)\\MSSQLLocalDB", description="Database server address"
    )
    database: str = Field(default="AdventureWorksLT2019", description="Database name")
    username: str = Field(default="sa", description="Database username")
    password: str = Field(default="1234567890", description="Database password")
    port: int = Field(default=1143, description="Database port")
    pool_size: int = Field(default=5, description="Connection pool size")
    timeout: int = Field(default=30, description="Connection timeout in seconds")


class ChatRequest(BaseModel):
    query: str = Field(..., description="The user's input query")
    history: List[ChatMessage] = Field(
        default_factory=list, description="Previous conversation history"
    )
    connection_string: ConnectionConfig = Field(
        ..., description="Database connection config"
    )
    model: str = Field(
        default="meta-llama/llama-4-scout-17b-16e-instruct",
        description="LLM model name",
    )


@router.post("/", response_model=ApiResult)
async def handle_chat(request: ChatRequest) -> ApiResult:
    try:
        conn = request.connection_string

        final_state = await run_chat_pipeline(
            user_query=request.query,
            history=[msg.model_dump() for msg in request.history],
            connection=conn.model_dump(),
            model_name=request.model,
        )

        response_text = final_state.get(
            "user_facing_response", "No response generated."
        )

        return ApiResult(
            success=True,
            message="Processed successfully.",
            data={"response": response_text},
        )

    except AppBaseException as app_exc:
        return ApiResult(success=False, message=str(app_exc), data=None)
    except Exception as exc:
        return ApiResult(
            success=False,
            message=f"An unexpected error occurred: {str(exc)}",
            data=None,
        )
