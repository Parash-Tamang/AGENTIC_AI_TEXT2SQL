"""
Pipeline Initialization - Set up prompt client and inject into nodes

Usage:
    from src.agent.prompt.pipeline import initialize_pipeline, initialize_pipeline_sync

    # Async
    pipeline = await initialize_pipeline(
        base_url="http://192.168.40.121:5197",
        connection_id="9DD2E9F0-4293-4E55-8E88-6FE881E5FC89"
    )

    # Sync
    pipeline = initialize_pipeline_sync(
        base_url="http://192.168.40.121:5197",
        connection_id="9DD2E9F0-4293-4E55-8E88-6FE881E5FC89"
    )

    # Use pipeline.prompt_client in your nodes
"""

from src.agent.prompt.client import AgentPromptClient


class PipelineContext:
    """Pipeline context that holds shared resources"""

    def __init__(self, prompt_client: AgentPromptClient):
        self.prompt_client = prompt_client


async def initialize_pipeline(
    base_url: str = "http://192.168.40.121:5197",
    connection_id: str = "9DD2E9F0-4293-4E55-8E88-6FE881E5FC89",
) -> PipelineContext:
    """
    Initialize the pipeline with a prompt client.

    Args:
        base_url: Base URL of the API
        connection_id: Connection ID from the database

    Returns:
        PipelineContext with initialized prompt client

    Example:
        pipeline = await initialize_pipeline(
            base_url="http://192.168.40.121:5197",
            connection_id="9DD2E9F0-4293-4E55-8E88-6FE881E5FC89"
        )
        prompt = pipeline.prompt_client.get_system_prompt("sql_generator")
    """
    prompt_client = AgentPromptClient(base_url=base_url, connection_id=connection_id)

    # Load all prompts from the API
    success = await prompt_client.load_all()
    if not success:
        raise RuntimeError(
            f"Failed to initialize pipeline: could not load prompts from {base_url}"
        )

    return PipelineContext(prompt_client=prompt_client)


def initialize_pipeline_sync(
    base_url: str = "http://192.168.40.121:5197",
    connection_id: str = "9DD2E9F0-4293-4E55-8E88-6FE881E5FC89",
) -> PipelineContext:
    """
    Initialize the pipeline with a prompt client (synchronous version).

    Args:
        base_url: Base URL of the API
        connection_id: Connection ID from the database

    Returns:
        PipelineContext with initialized prompt client

    Example:
        pipeline = initialize_pipeline_sync(
            base_url="http://192.168.40.121:5197",
            connection_id="9DD2E9F0-4293-4E55-8E88-6FE881E5FC89"
        )
        prompt = pipeline.prompt_client.get_system_prompt("sql_generator")
    """
    prompt_client = AgentPromptClient(base_url=base_url, connection_id=connection_id)

    # Load all prompts from the API (sync version)
    success = prompt_client.load_all_sync()
    if not success:
        raise RuntimeError(
            f"Failed to initialize pipeline: could not load prompts from {base_url}"
        )

    return PipelineContext(prompt_client=prompt_client)


def promptFunction():
    """Load and return all local prompts in ApiResult format.

    Returns prompts from local store without calling API.
    Returns same format as real prompt API.

    Example:
        result = promptFunction()
        print(result.model_dump())
    """
    from src.api_response import ApiResult
    from src.agent.prompt import (
        INTENT_CLASSIFIER_SYSTEM,
        REFINER_SYSTEM,
        DECOMPOSITION_SYSTEM,
        GENERATE_RESPONSE_SYSTEM,
        SCHEMA_SEED_FILTER_SYSTEM,
        SCHEMA_SUFFICIENCY_SYSTEM,
        SQL_GENERATION_SYSTEM,
        SQL_RESULTS_VALIDATOR_SYSTEM,
        SQL_VALIDATION_SYSTEM,
        VIEWS_GRADER_SYSTEM,
        VIEWS_SUGGESTION_SYSTEM,
    )

    try:
        prompts = {
            "intent_classifier": INTENT_CLASSIFIER_SYSTEM,
            "refiner": REFINER_SYSTEM,
            "decomposition": DECOMPOSITION_SYSTEM,
            "generate_response": GENERATE_RESPONSE_SYSTEM,
            "schema_seed_filter": SCHEMA_SEED_FILTER_SYSTEM,
            "schema_sufficiency": SCHEMA_SUFFICIENCY_SYSTEM,
            "sql_generator": SQL_GENERATION_SYSTEM,
            "sql_results_validator": SQL_RESULTS_VALIDATOR_SYSTEM,
            "sql_validator": SQL_VALIDATION_SYSTEM,
            "views_grader": VIEWS_GRADER_SYSTEM,
            "views_suggestion": VIEWS_SUGGESTION_SYSTEM,
        }

        return ApiResult(
            success=True,
            message="Prompts loaded successfully",
            data=prompts,
        )
    except Exception as e:
        return ApiResult(
            success=False,
            message=f"Error loading prompts: {str(e)}",
            data=None,
        )
