from pydantic import BaseModel


class GraphSettings(BaseModel):
    # Graph persistence directory
    persist_directory: str = "assets/graph"


# Singleton default settings — override per environment
DEFAULT_GRAPH_SETTINGS = GraphSettings()

__all__ = ["GraphSettings", "DEFAULT_GRAPH_SETTINGS"]
