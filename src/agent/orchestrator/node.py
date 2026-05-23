from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseNode(ABC):
    """Base contract for all workflow nodes.

    Nodes must be awaitable (async) and accept a mutable `state` dict.
    They should return the updated `state` dict (or mutate in-place).
    """

    name: str = "base"

    @abstractmethod
    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the node logic using and updating `state`.

        Implementations MUST NOT perform orchestration decisions
        (those live in `router.py` / graph topology).
        """
        raise NotImplementedError()


__all__ = ["BaseNode"]
