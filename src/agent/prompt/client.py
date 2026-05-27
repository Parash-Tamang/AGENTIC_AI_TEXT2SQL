"""
AgentPromptClient - Fetch prompts from API with caching
"""

import httpx
from typing import Optional, Dict, Any
from pydantic import BaseModel


class PromptFunction(BaseModel):
    """Represents a single prompt function returned from API"""

    functionId: str
    functionName: str
    systemPrompt: str


class PromptResponse(BaseModel):
    """Response from prompt API"""

    success: bool
    connectionId: str
    database: str
    functions: list[PromptFunction]


class AgentPromptClient:
    """
    Client to fetch and cache prompts from the API.

    Usage:
        client = AgentPromptClient(base_url="http://localhost:5197", connection_id="9DD2E9F0-4293-4E55-8E88-6FE881E5FC89")
        client.load_all()
        prompt = client.get_system_prompt("sql_generator")
    """

    def __init__(self, base_url: str, connection_id: str):
        """
        Initialize prompt client.

        Args:
            base_url: Base URL of the API (e.g., "http://192.168.40.121:5197")
            connection_id: Connection ID from the database (e.g., "9DD2E9F0-4293-4E55-8E88-6FE881E5FC89")
        """
        self.base_url = base_url.rstrip("/")
        self.connection_id = connection_id
        self._cache: Dict[str, str] = {}
        self._loaded = False
        self._connection_id_response: Optional[str] = None

    async def load_all(self) -> bool:
        """
        Load all prompts from the API and cache them.

        Returns:
            True if successful, False otherwise
        """
        try:
            async with httpx.AsyncClient() as client:
                url = f"{self.base_url}/api/agent/V1/prompt-engine/Get-DB-Functions"
                payload = {"connectionId": self.connection_id}
                response = await client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()

                data = response.json()
                if data.get("success"):
                    # Parse the response
                    result = PromptResponse(**data)
                    self._connection_id_response = result.connectionId

                    # Cache all prompts by function name
                    for func in result.functions:
                        self._cache[func.functionName] = func.systemPrompt

                    self._loaded = True
                    return True
        except Exception as e:
            print(f"Failed to load prompts: {e}")
            return False

        return False

    def load_all_sync(self) -> bool:
        """
        Synchronous version of load_all().

        Returns:
            True if successful, False otherwise
        """
        try:
            with httpx.Client() as client:
                url = f"{self.base_url}/api/agent/V1/prompt-engine/Get-DB-Functions"
                payload = {"connectionId": self.connection_id}
                response = client.post(url, json=payload, timeout=10.0)
                response.raise_for_status()

                data = response.json()
                if data.get("success"):
                    # Parse the response
                    result = PromptResponse(**data)
                    self._connection_id_response = result.connectionId

                    # Cache all prompts by function name
                    for func in result.functions:
                        self._cache[func.functionName] = func.systemPrompt

                    self._loaded = True
                    return True
        except Exception as e:
            print(f"Failed to load prompts: {e}")
            return False

        return False

    def get_system_prompt(self, prompt_name: str) -> Optional[str]:
        """
        Get a cached system prompt by name.

        Args:
            prompt_name: Name of the prompt (e.g., "sql_generator", "intent_classifier")

        Returns:
            The system prompt text, or None if not found
        """
        if not self._loaded:
            raise RuntimeError(
                "Prompts not loaded. Call load_all() or load_all_sync() first."
            )
        return self._cache.get(prompt_name)

    def get_system_prompt_or_default(self, prompt_name: str, default: str = "") -> str:
        """
        Get a cached system prompt by name, with a default fallback.

        Args:
            prompt_name: Name of the prompt
            default: Default prompt text if not found

        Returns:
            The system prompt text, or default if not found
        """
        if not self._loaded:
            return default
        return self._cache.get(prompt_name, default)

    @property
    def is_loaded(self) -> bool:
        """Check if prompts have been loaded"""
        return self._loaded

    @property
    def connection_id_response(self) -> Optional[str]:
        """Get the connection ID from the API response"""
        return self._connection_id_response

    @property
    def available_prompts(self) -> list[str]:
        """Get list of all cached prompt names"""
        return list(self._cache.keys())

    def clear_cache(self):
        """Clear the cached prompts"""
        self._cache.clear()
        self._loaded = False
        self._connection_id = None
