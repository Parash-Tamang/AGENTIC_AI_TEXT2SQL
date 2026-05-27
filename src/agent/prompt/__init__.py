# Centralized Prompt Management
# All prompts are exported from this __init__.py file for easy access

from src.agent.prompt.intent_prompt import INTENT_CLASSIFIER_SYSTEM
from src.agent.prompt.refiner import REFINER_SYSTEM
from src.agent.prompt.decomposition import DECOMPOSITION_SYSTEM
from src.agent.prompt.generate_response import GENERATE_RESPONSE_SYSTEM
from src.agent.prompt.schema_agent import (
    SCHEMA_SEED_FILTER_SYSTEM,
    SCHEMA_SUFFICIENCY_SYSTEM,
)
from src.agent.prompt.sql_generator import SQL_GENERATION_SYSTEM
from src.agent.prompt.sql_results_validator import SQL_RESULTS_VALIDATOR_SYSTEM
from src.agent.prompt.sql_validator import SQL_VALIDATION_SYSTEM
from src.agent.prompt.views_agent import (
    VIEWS_GRADER_SYSTEM,
    VIEWS_SUGGESTION_SYSTEM,
)

# Pipeline and Client
from src.agent.prompt.client import AgentPromptClient, PromptFunction, PromptResponse
from src.agent.prompt.pipeline import (
    PipelineContext,
    initialize_pipeline,
    initialize_pipeline_sync,
)

__all__ = [
    # Prompts
    "INTENT_CLASSIFIER_SYSTEM",
    "REFINER_SYSTEM",
    "DECOMPOSITION_SYSTEM",
    "GENERATE_RESPONSE_SYSTEM",
    "SCHEMA_SEED_FILTER_SYSTEM",
    "SCHEMA_SUFFICIENCY_SYSTEM",
    "SQL_GENERATION_SYSTEM",
    "SQL_RESULTS_VALIDATOR_SYSTEM",
    "SQL_VALIDATION_SYSTEM",
    "VIEWS_GRADER_SYSTEM",
    "VIEWS_SUGGESTION_SYSTEM",
    # Client
    "AgentPromptClient",
    "PromptFunction",
    "PromptResponse",
    # Pipeline
    "PipelineContext",
    "initialize_pipeline",
    "initialize_pipeline_sync",
]
