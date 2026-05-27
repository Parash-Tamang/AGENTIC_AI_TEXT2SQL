"""Utilities for resolving system prompts from a prompt client or defaults.

Nodes can call resolve_system_prompt(state, prompt_name, default) to obtain the
system prompt to pass to the LLM. This centralises the logic and reduces
duplication across nodes.

Supports:
  - AgentPromptClient (real API client)
  - LocalPromptClient (local prompts wrapper)
  - Any object with get_system_prompt() or get_system_prompt_or_default() methods
"""

from typing import Any


def resolve_system_prompt(state: Any, prompt_name: str, default: str) -> str:
    """Return a system prompt string.

    Priority:
      1. If state contains a `prompt_client` and it exposes
         `get_system_prompt_or_default`, use that.
      2. If `prompt_client.get_system_prompt` exists, try that and fall back
         to `default`.
      3. Otherwise return `default`.

    The helper is defensive and won't raise if prompt_client misbehaves.

    Compatible with:
      - AgentPromptClient (real API client)
      - LocalPromptClient (local prompts wrapper from chat_controller)
      - Any custom prompt client with get_system_prompt() methods
    """
    try:
        prompt_client = None
        if isinstance(state, dict):
            prompt_client = state.get("prompt_client")
        elif hasattr(state, "model_dump"):
            dumped = state.model_dump()
            if isinstance(dumped, dict):
                prompt_client = dumped.get("prompt_client")
        else:
            # fallback: try attribute access
            prompt_client = getattr(state, "prompt_client", None)

        if not prompt_client:
            return default

        # Prefer the safe API that returns default when not loaded
        if hasattr(prompt_client, "get_system_prompt_or_default"):
            try:
                return prompt_client.get_system_prompt_or_default(prompt_name, default)
            except Exception:
                return default

        # Fallback to simple getter
        if hasattr(prompt_client, "get_system_prompt"):
            try:
                val = prompt_client.get_system_prompt(prompt_name)
                return val or default
            except Exception:
                return default

        return default
    except Exception:
        return default
