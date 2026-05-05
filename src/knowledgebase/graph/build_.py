import json
import logging
import os
import networkx as nx

logger = logging.getLogger(__name__)


def build_schema_graph(schema_file: str, collection_name: str, base_dir: str) -> str:

    collection_dir = os.path.join(base_dir, collection_name.lower())
    os.makedirs(collection_dir, exist_ok=True)

    # ── GraphML instead of pickle (portable, .NET readable) ──
    graph_path = os.path.join(collection_dir, f"{collection_name}.graphml")

    with open(schema_file, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # ── Directed graph (parent → child, reflects FK direction) ──
    graph = nx.DiGraph()

    for table in schema:
        table_name = table["table_name"]
        graph.add_node(table_name, type="table")

        for column in table["columns"]:
            col_name = column["name"]

            # Add column as node linked to its table
            col_node = f"{table_name}.{col_name}"
            graph.add_node(col_node, type="column", table=table_name)
            graph.add_edge(table_name, col_node)

            # Add FK relation edge with from/to columns
            relation = column.get("relation")
            if relation:
                parts = relation.split(".")
                if len(parts) == 2:
                    ref_table, ref_col = parts
                else:
                    ref_table = parts[0]
                    ref_col = "id"

                graph.add_node(ref_table, type="table")
                graph.add_edge(
                    table_name, ref_table, from_col=col_name, to_col=ref_col, type="fk"
                )

    # ── Save as GraphML (portable) ──
    nx.write_graphml(graph, graph_path)
    logger.info("Graph saved → %s", graph_path)
    return graph_path
