# src/knowledgebase/retriever.py

import json
import logging
import networkx as nx
from collections import deque

log = logging.getLogger("knowledgebase.retriever")


def bfs_schema_with_joins(
    graph: nx.DiGraph,  # ✅ passed in — loaded at startup
    schema_map: dict,  # ✅ passed in — loaded at startup
    seed_tables: list[str],
    max_hops: int = 2,
    token_limit: int = 8000,
) -> dict:
    """
    BFS from seed tables to pull related tables + join paths.
    No disk I/O — graph and schema_map are pre-loaded at startup.
    """

    log.info(f"BFS started — seeds: {seed_tables}, max_hops: {max_hops}")

    # ── Validate seeds ────────────────────────────────────────
    valid_seeds = [
        s
        for s in seed_tables
        if graph.has_node(s) and graph.nodes[s].get("type") == "table"
    ]

    if not valid_seeds:
        log.warning(f"No valid seed tables found from: {seed_tables}")
        return {"tables": [], "schema": [], "joins": [], "token_estimate": 0}

    # ── BFS ───────────────────────────────────────────────────
    undirected = graph.to_undirected()
    visited = set()
    queue = deque([(s, 0) for s in valid_seeds])

    while queue:
        node, hop = queue.popleft()

        if node in visited or hop > max_hops:
            continue
        if graph.nodes.get(node, {}).get("type") != "table":
            continue

        visited.add(node)
        log.debug(f"Visited: '{node}' at hop {hop}")

        for neighbor in undirected.neighbors(node):
            if (
                neighbor not in visited
                and graph.nodes.get(neighbor, {}).get("type") == "table"
            ):
                queue.append((neighbor, hop + 1))

    log.info(f"BFS complete — {len(visited)} tables: {visited}")

    # ── FK index (avoid full edge scan per table) ─────────────
    fk_index: dict[str, list] = {}
    for u, v, data in graph.edges(data=True):
        if data.get("type") == "fk":
            fk_index.setdefault(u, []).append((u, v, data))
            fk_index.setdefault(v, []).append((u, v, data))

    # ── Build context ─────────────────────────────────────────
    context_tables = []
    total_tokens = 0
    all_joins = set()

    for table_name in visited:

        if table_name not in schema_map:
            log.warning(f"'{table_name}' in graph but not in schema — skipping")
            continue

        joins = []
        for u, v, data in fk_index.get(table_name, []):
            if u in visited and v in visited:
                join = f"{u}.{data['from_col']} = {v}.{data['to_col']}"
                joins.append(join)
                all_joins.add(join)

        entry = {
            "table": table_name,
            "columns": schema_map[table_name]["columns"],
            "joins": joins,
        }
        context_tables.append(entry)

        total_tokens += len(json.dumps(entry)) // 4
        if total_tokens >= token_limit:
            log.warning(f"Token limit reached at '{table_name}' — truncating")
            break

    log.info(
        f"Context ready — tables: {len(context_tables)}, "
        f"joins: {len(all_joins)}, ~{total_tokens} tokens"
    )

    return {
        "tables": [t["table"] for t in context_tables],
        "schema": context_tables,
        "joins": list(all_joins),
        "token_estimate": total_tokens,
    }
