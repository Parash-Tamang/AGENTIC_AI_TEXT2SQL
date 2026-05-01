from pydantic import BaseModel


class VectorSettings(BaseModel):
    # ChromaDB persistence directory
    persist_directory: str = "assets/vectordb"

    # Collection names
    schema_collection: str = "table_schemas"
    views_collection: str = "view_schemas"

    # Sentence-transformers model
    embedding_model: str = "all-MiniLM-L6-v2"

    # Number of results to return in similarity search
    top_k: int = 5


# Singleton default settings — override per environment
DEFAULT_SETTINGS = VectorSettings()

__all__ = ["VectorSettings", "DEFAULT_SETTINGS"]
