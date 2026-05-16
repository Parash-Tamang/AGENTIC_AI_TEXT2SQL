from pydantic import BaseModel
import os
import logging
import networkx as nx

log = logging.getLogger("graph.manager")


class GraphSettings(BaseModel):
    persist_directory: str = "assets/graph"


class GraphManager:

    def __init__(self, settings: GraphSettings = GraphSettings()):
        self.settings = settings
        self.graphs = {}  # { db_id: nx.DiGraph }

    # ── Load all at startup ───────────────────────────────────

    def load_all(self):
        base = self.settings.persist_directory

        if not os.path.exists(base):
            log.warning(f"Graph directory not found: {base}")
            return

        for collection in os.listdir(base):
            collection_dir = os.path.join(base, collection)

            if not os.path.isdir(collection_dir):
                continue

            graphml_file = self._find_graphml(collection_dir)
            if not graphml_file:
                log.warning(f"No .graphml in '{collection}' — skipping")
                continue

            self._load_graph(collection, graphml_file)

        log.info(f"GraphManager ready — {len(self.graphs)} graph(s) loaded")

    # ── Hot load single ───────────────────────────────────────

    def load_one(self, db_id: str):
        base = self.settings.persist_directory
        collection_dir = os.path.join(base, db_id.lower())

        if not os.path.exists(collection_dir):
            raise FileNotFoundError(f"No folder found for '{db_id}'")

        graphml_file = self._find_graphml(collection_dir)
        if not graphml_file:
            raise FileNotFoundError(f"No .graphml found for '{db_id}'")

        self._load_graph(db_id, graphml_file)

    # ── Unload ────────────────────────────────────────────────

    def unload(self, db_id: str):
        if db_id in self.graphs:
            self.graphs.pop(db_id)
            log.info(f"Unloaded '{db_id}' from memory")
        else:
            log.warning(f"'{db_id}' was not loaded")

    # ── Getters ───────────────────────────────────────────────

    def get_graph(self, db_id: str) -> nx.DiGraph:
        if db_id not in self.graphs:
            log.warning(f"'{db_id}' not in memory — lazy loading...")
            self.load_one(db_id)
        return self.graphs[db_id]

    def list_collections(self) -> list[str]:
        return list(self.graphs.keys())

    def is_loaded(self, db_id: str) -> bool:
        return db_id in self.graphs

    # ── Internal ──────────────────────────────────────────────

    def _find_graphml(self, directory: str) -> str | None:
        for f in os.listdir(directory):
            if f.endswith(".graphml"):
                return os.path.join(directory, f)
        return None

    def _load_graph(self, db_id: str, graphml_path: str):
        try:
            self.graphs[db_id] = nx.read_graphml(graphml_path)
            log.info(
                f"Loaded '{db_id}' ← {os.path.basename(graphml_path)} | "
                f"nodes: {self.graphs[db_id].number_of_nodes()}, "
                f"edges: {self.graphs[db_id].number_of_edges()}"
            )
        except Exception as e:
            log.error(f"Failed to load '{db_id}': {e}")
            raise


# ── Singletons ────────────────────────────────────────────────

DEFAULT_GRAPH_SETTINGS = GraphSettings()
graph_manager = GraphManager(settings=DEFAULT_GRAPH_SETTINGS)

__all__ = ["GraphSettings", "GraphManager", "DEFAULT_GRAPH_SETTINGS", "graph_manager"]
