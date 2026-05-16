import json
import logging
import os
import networkx as nx

logger = logging.getLogger(__name__)


def build_schema_graph(schema_file: str, collection_name: str, base_dir: str) -> str:

    collection_dir = os.path.join(base_dir, collection_name.lower())
    os.makedirs(collection_dir, exist_ok=True)

    graph_path = os.path.join(collection_dir, f"{collection_name}.graphml")

    with open(schema_file, "r", encoding="utf-8") as f:
        schema = json.load(f)

    graph = nx.DiGraph()

    for table in schema:
        table_name = table["table_name"]
        graph.add_node(table_name, type="table")

        for column in table["columns"]:
            col_name = column["name"]
            col_node = f"{table_name}.{col_name}"

            # Convert None values to empty strings for GraphML compatibility
            col_type = column.get("type") or ""
            description = column.get("description") or ""

            graph.add_node(
                col_node,
                type="column",
                table=table_name,
                col_type=col_type,
                description=description,
            )
            graph.add_edge(table_name, col_node)

            relation = column.get("relation")
            if relation:
                parts = relation.split(".")
                if len(parts) == 2:
                    ref_table, ref_col = parts
                else:
                    ref_table = parts[0]
                    ref_col = "id"

                graph.add_node(ref_table, type="table")
                # Ensure from_col and to_col are strings for GraphML compatibility
                graph.add_edge(
                    table_name,
                    ref_table,
                    from_col=str(col_name),
                    to_col=str(ref_col),
                    type="fk",
                )

    nx.write_graphml(graph, graph_path)
    logger.info("Graph saved → %s", graph_path)
    return graph_path
