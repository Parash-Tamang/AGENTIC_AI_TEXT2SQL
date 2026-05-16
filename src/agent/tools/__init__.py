"""
Agent tools package.

Public API:
  - set_connection_config() — set connection on startup
  - get_connection_config() — get active connection config
  - reset_connection_config() — clear config (for testing)
  - TOOLS — simplified tool definitions for the LLM
  - dispatch() — execute tool by name
  - dispatch_to_tool_result() — wrapper for Anthropic responses
"""

from src.agent.tools.config import (
    set_connection_config,
    get_connection_config,
    reset_connection_config,
)
from src.agent.tools.definitions import TOOLS
from src.agent.tools.executor import dispatch, dispatch_to_tool_result

__all__ = [
    "set_connection_config",
    "get_connection_config",
    "reset_connection_config",
    "TOOLS",
    "dispatch",
    "dispatch_to_tool_result",
]
