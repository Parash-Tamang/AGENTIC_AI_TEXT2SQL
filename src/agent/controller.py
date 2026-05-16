"""Placeholder controller for Anthropic integration."""


class ControllerConfig:
    """Agent controller configuration."""

    def __init__(self, model="claude-3-5-sonnet", max_tokens=2048, max_iterations=10):
        self.model = model
        self.max_tokens = max_tokens
        self.max_iterations = max_iterations


class ControllerResponse:
    """Response from controller."""

    def __init__(self, answer="", chat_history=None, iterations=0, error=None):
        self.answer = answer
        self.chat_history = chat_history or []
        self.iterations = iterations
        self.error = error


def query_agent(user_query, **kwargs):
    """Placeholder query function."""
    return ControllerResponse(answer="", chat_history=[], iterations=0)
