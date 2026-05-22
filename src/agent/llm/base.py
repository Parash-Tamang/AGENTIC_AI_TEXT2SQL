from abc import ABC, abstractmethod
from typing import Optional, List, Dict


class BaseLLM(ABC):
    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        memory: Optional[List[Dict[str, str]]] = None,
        tools: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Generate a response from the LLM.
        Must be implemented by all providers.

        Args:
            system_prompt: System message for the LLM
            user_prompt: User message for the LLM
            memory: Optional list of memory context dicts with 'role' and 'content' keys
                   Example: [{"role": "user_memory", "content": "..."}, ...]
        """
        pass
