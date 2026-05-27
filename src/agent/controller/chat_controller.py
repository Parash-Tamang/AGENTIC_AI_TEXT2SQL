from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
from src.agent.prompt import initialize_pipeline_sync, AgentPromptClient
from src.agent.prompt.pipeline import promptFunction

from src.api_response import ApiResult
from src.exceptions import AppBaseException
from src.agent.orchestrator.chat import run_chat_pipeline
from src.agent.memory.session_context import SessionContext, extract_from_state


class LocalPromptClient:
    """Wrapper to use local prompts as a prompt client."""

    def __init__(self, prompts_dict):
        self._cache = prompts_dict
        self.is_loaded = True

    def get_system_prompt(self, prompt_name: str) -> str:
        """Get a prompt by name."""
        return self._cache.get(prompt_name, "")

    def get_system_prompt_or_default(self, prompt_name: str, default: str = "") -> str:
        """Get a prompt by name or return default."""
        return self._cache.get(prompt_name, default)


router = APIRouter(prefix="/chat", tags=["Chat Environment"])


class ChatMessage(BaseModel):
    role: str = Field(
        description="Role of the message sender, e.g., 'user' or 'assistant'"
    )
    content: str = Field(description="The text content of the message")


class ConnectionConfig(BaseModel):
    db_type: str = Field(default="mssql", description="Database engine type")
    connection_id: str = Field(
        default="9DD2E9F0-4293-4E55-8E88-6FE881E5FC89",
        description="Unique connection ID for prompt API",
    )
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
    user_id: str = Field(..., description="Unique identifier for the user")
    query: str = Field(..., description="The user's input query")
    user_role: str = Field(
        ..., description="Caller role for RBAC (e.g., customer, sales, admin)"
    )
    history: List[ChatMessage] = Field(
        default_factory=list, description="Previous conversation history"
    )
    session_context: SessionContext = Field(
        ..., description="Session context payload for the chat request"
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
        session_context = request.session_context

        # Merge any DB info from session_context into connection dict so pipeline uses them
        # connection_dict = conn.model_dump()
        # if getattr(session_context, "db_id", None):
        #     connection_dict["connection_id"] = session_context.db_id
        # if getattr(session_context, "db_type", None):
        #     connection_dict["db_type"] = session_context.db_type

        # Initialize prompt pipeline from API (call API only from controller)
        # prompt_client = initialize_pipeline_sync(
        #     base_url="http://192.168.40.121:5197",
        #     connection_id=conn.connection_id,
        # ).prompt_client

        # Use local prompts instead
        prompts_result = promptFunction()
        if not prompts_result.success:
            return ApiResult(success=False, message="Failed to load prompts", data=None)

        # Create a local prompt client wrapper
        prompt_client = LocalPromptClient(prompts_result.data)

        # Build connection dict and include minimal connection-context
        connection_dict = conn.model_dump()
        # Ensure caller user id is present in the connection payload (if not provided)
        if not connection_dict.get("user_id") and getattr(request, "user_id", None):
            connection_dict["user_id"] = request.user_id
        # Include the user query in the connection context for downstream tracing/auditing
        connection_dict["query"] = request.query

        effective_role = request.user_role

        final_state = await run_chat_pipeline(
            user_query=request.query,
            history=[msg.model_dump() for msg in request.history],
            connection=connection_dict,
            model_name=request.model,
            prompt_client=prompt_client,
            session_context=session_context,
            user_role=effective_role,
        )

        response_text = final_state.get(
            "user_facing_response", "No response generated."
        )
        response_session_context = extract_from_state(final_state)

        return ApiResult(
            success=True,
            message="Processed successfully.",
            data={
                "response": response_text,
                "session_context": response_session_context.model_dump(),
            },
        )

    except ValueError as exc:
        message = str(exc)
        if "Unknown role:" in message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Role does not exist.",
            ) from exc
        if "user_role is required" in message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_role is required.",
            ) from exc
        return ApiResult(success=False, message=message, data=None)

    except AppBaseException as app_exc:
        return ApiResult(success=False, message=str(app_exc), data=None)
    except Exception as exc:
        return ApiResult(
            success=False,
            message=f"An unexpected error occurred: {str(exc)}",
            data=None,
        )
