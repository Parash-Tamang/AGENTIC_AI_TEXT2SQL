from abc import ABC, abstractmethod
from typing import Any, Optional, List, Dict


class BaseLLM(ABC):
    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        memory: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, str]]] = None,
        json_mode: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Generate a response from the LLM.
        Must be implemented by all providers.

        Args:
            system_prompt: System message for the LLM
            user_prompt: User message for the LLM
            memory: Optional list of memory context dicts with 'role' and 'content' keys
                   Example: [{"role": "user_memory", "content": "..."}, ...]
                 json_mode: When True, the provider should return JSON-compatible output.
                 response_format: Optional structured response schema for providers that support it.
        """
        pass
