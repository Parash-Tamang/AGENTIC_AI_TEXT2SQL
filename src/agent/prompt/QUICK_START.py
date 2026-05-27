"""
Quick Start Guide for Using the Prompt Management System

This guide shows agents how to use prompts in their code.
"""

# ============================================================================
# OPTION 1: Using Prompt Manager (Recommended for Agents)
# ============================================================================

from src.agent.prompt.prompt_manager import fetch_prompt, fetch_prompt_safe

# Get a prompt (uses custom if set, else default)
intent_prompt = fetch_prompt("intent_classifier")

# Safe fetch with fallback
prompt = fetch_prompt_safe("my_prompt", default="default text if not found")

# Use in LLM call
response = llm.generate(system_prompt=intent_prompt, user_prompt=user_input)


# ============================================================================
# OPTION 2: Direct Import from __init__.py (Legacy)
# ============================================================================

from src.agent.prompt import INTENT_CLASSIFIER_SYSTEM, REFINER_SYSTEM

# Still works, but won't respect custom prompts set via API
prompt = INTENT_CLASSIFIER_SYSTEM


# ============================================================================
# OPTION 3: Using Prompt State Directly
# ============================================================================

from src.agent.prompt.prompt_manager import get_global_prompt_state

state = get_global_prompt_state()
prompt = state.get_prompt("intent_classifier")
all_prompts = state.get_all_prompts()
is_custom = state.is_using_custom("intent_classifier")


# ============================================================================
# EXAMPLE: Updated Agent Code
# ============================================================================


class IntentClassifier:
    def __init__(self, llm):
        self.llm = llm
        # Get prompt (will use custom if set via API, else default)
        self.system_prompt = fetch_prompt("intent_classifier")

    async def classify(self, query: str) -> dict:
        response = self.llm.generate(
            system_prompt=self.system_prompt,
            user_prompt=json.dumps({"query": query}),
            response_format={"type": "json_schema"},
        )
        return response


# ============================================================================
# EXAMPLE: Setting Custom Prompts Programmatically
# ============================================================================

from src.agent.prompt.prompt_manager import set_custom_prompts

# Set custom prompts (maybe from config or environment)
custom_prompts = {
    "intent_classifier": "Your custom intent classifier prompt",
    "query_refiner": "Your custom query refiner prompt",
}

set_custom_prompts(custom_prompts)

# Now all agents will use these custom prompts
prompt = fetch_prompt("intent_classifier")  # Gets custom version


# ============================================================================
# EXAMPLE: API Call to Update Prompts
# ============================================================================

import requests

# Update prompts via API
response = requests.post(
    "http://localhost:8000/chat/api/prompt/AdventureWorksLT2019/update",
    json={
        "prompts": {
            "intent_classifier": "New custom prompt",
            "query_refiner": "Another new prompt",
        }
    },
)

# All subsequent fetch_prompt() calls will use these custom prompts


# ============================================================================
# API QUICK REFERENCE
# ============================================================================

"""
GET /chat/api/prompt/{databasename}
  - Get all active prompts (custom or defaults)
  - Optional: ?prompt_id=<id> to get specific prompt

GET /chat/api/prompt/{databasename}/defaults
  - Get all default prompts (read-only reference)

POST /chat/api/prompt/{databasename}/update
  - Update custom prompts
  - Body: {"prompts": {"prompt_id": "new text", ...}}

POST /chat/api/prompt/{databasename}/reset
  - Reset to defaults
  - Body: {"reset_all": true} or {"reset_all": false, "prompt_ids": [...]}

GET /chat/api/prompt/{databasename}/info
  - Get info about all prompts and their sources (custom vs default)
"""

# ============================================================================
# MIGRATION PATH
# ============================================================================

# OLD CODE:
# from src.agent.nodes.intent_classifier import INTENT_CLASSIFIER_SYSTEM
# prompt = INTENT_CLASSIFIER_SYSTEM

# NEW CODE:
# from src.agent.prompt.prompt_manager import fetch_prompt
# prompt = fetch_prompt("intent_classifier")

# Benefits:
# ✓ Respects custom prompts set via API
# ✓ Single source of truth
# ✓ No import from nodes
# ✓ Automatic fallback to defaults
