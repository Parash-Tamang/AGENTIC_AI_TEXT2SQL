import json
import logging
import networkx as nx
from collections import deque

log = logging.getLogger("knowledgebase.retriever")


def bfs_schema_with_joins(
    graph: nx.DiGraph,
    seed_tables: list[str],
    max_hops: int = 2,
    token_limit: int = 8000,
) -> dict:
    log.info(f"BFS started — seeds: {seed_tables}, max_hops: {max_hops}")

    visited = _bfs_tables(graph, seed_tables, max_hops)
    if not visited:
        return {"tables": [], "schema": [], "joins": [], "token_estimate": 0}

    fk_index = _build_fk_index(graph)
    return _build_context(graph, visited, fk_index, token_limit)


# ── BFS ───────────────────────────────────────────────────────


def _bfs_tables(
    graph: nx.DiGraph,
    seed_tables: list[str],
    max_hops: int,
) -> set[str]:

    valid_seeds = [
        s
        for s in seed_tables
        if graph.has_node(s) and graph.nodes[s].get("type") == "table"
    ]

    if not valid_seeds:
        log.warning(f"No valid seed tables found from: {seed_tables}")
        return set()

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
    return visited


# ── FK index ──────────────────────────────────────────────────


def _build_fk_index(graph: nx.DiGraph) -> dict[str, list]:
    fk_index: dict[str, list] = {}

    for u, v, data in graph.edges(data=True):
        if data.get("type") == "fk":
            fk_index.setdefault(u, []).append((u, v, data))
            fk_index.setdefault(v, []).append((u, v, data))

    return fk_index


# ── Build context ─────────────────────────────────────────────


def _build_context(
    graph: nx.DiGraph,
    visited: set[str],
    fk_index: dict[str, list],
    token_limit: int,
) -> dict:

    context_tables = []
    total_tokens = 0
    all_joins = set()

    for table_name in visited:

        columns = [
            {
                "name": n.split(".")[1],
                "type": graph.nodes[n].get("col_type", ""),
                "description": graph.nodes[n].get("description", ""),
            }
            for n in graph.successors(table_name)
            if graph.nodes[n].get("type") == "column"
        ]

        if not columns:
            log.warning(f"'{table_name}' has no column nodes in graph — skipping")
            continue

        joins = []
        for u, v, data in fk_index.get(table_name, []):
            if u in visited and v in visited:
                join = f"{u}.{data['from_col']} = {v}.{data['to_col']}"
                joins.append(join)
                all_joins.add(join)

        entry = {
            "table": table_name,
            "columns": columns,
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


# ── Format for prompt ─────────────────────────────────────────


def format_schema_for_prompt(bfs_result: dict) -> str:
    lines = ["## Relevant Schema\n"]

    for table in bfs_result["schema"]:
        lines.append(f"### {table['table']}")
        for col in table["columns"]:
            desc = col.get("description", "")
            col_type = col.get("type", "")
            lines.append(f"  - {col['name']} ({col_type}): {desc}")
        lines.append("")

    if bfs_result["joins"]:
        lines.append("## Join Paths")
        for join in bfs_result["joins"]:
            lines.append(f"  - {join}")

    return "\n".join(lines)
