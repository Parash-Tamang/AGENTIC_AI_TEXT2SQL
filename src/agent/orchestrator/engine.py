"""Graph execution engine."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Dict

from .topology import GRAPH, END_NODES, START_NODE
from .router import ROUTER_FNS

log = logging.getLogger(__name__)

NodeFn = Callable[[Dict[str, Any]], Dict[str, Any]]
RouterFn = Callable[[Dict[str, Any]], str]


class GraphEngine:
    def __init__(
        self,
        nodes: Dict[str, NodeFn],
        graph: Dict[str, dict] = GRAPH,
        routers: Dict[str, RouterFn] = ROUTER_FNS,
        start_node: str = START_NODE,
        end_nodes: frozenset[str] = END_NODES,
        max_steps: int = 50,
    ) -> None:
        self.nodes = nodes
        self.graph = graph
        self.routers = routers
        self.start_node = start_node
        self.end_nodes = end_nodes
        self.max_steps = max_steps

    async def run(self, state: Dict[str, Any]) -> Dict[str, Any]:
        current = self.start_node
        steps = 0

        while current is not None:
            if steps >= self.max_steps:
                raise RuntimeError(
                    f"Graph exceeded max_steps={self.max_steps}. "
                    f"Last node: {current}"
                )

            log.debug("[step %d] node=%s", steps, current)
            state = await self._run_node(current, state)
            current = await self._resolve_next(current, state)
            steps += 1

            if current in self.end_nodes:
                state = await self._run_node(current, state)
                break

        return state

    async def _run_node(self, name: str, state: Dict[str, Any]) -> Dict[str, Any]:
        node_fn = self.nodes.get(name)
        if node_fn is None:
            raise KeyError(f"No node registered for '{name}'")
        result = node_fn(state)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _resolve_next(self, current: str, state: Dict[str, Any]) -> str | None:
        edge = self.graph.get(current, {})

        if "next" in edge:
            return edge["next"]

        if "router" in edge:
            from .topology import ROUTERS

            router_name = edge["router"]
            router_fn = self.routers.get(router_name)
            if router_fn is None:
                raise KeyError(f"No router registered: '{router_name}'")

            route_key = router_fn(state)
            if inspect.isawaitable(route_key):
                route_key = await route_key

            router_map = ROUTERS.get(router_name, {})
            next_node = router_map.get(route_key)
            if (
                next_node is None
                and route_key not in self.graph
                and route_key not in self.end_nodes
            ):
                return route_key
            return next_node

        raise ValueError(f"Node '{current}' has no 'next' or 'router' in GRAPH")


__all__ = ["GraphEngine"]
