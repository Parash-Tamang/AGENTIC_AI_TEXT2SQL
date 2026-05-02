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

    @classmethod
    def for_database(
        cls, database_name: str, persist_dir: str = "assets/vectordb"
    ) -> "VectorSettings":
        """
        Create VectorSettings with collection names based on database name.

        Example:
            settings = VectorSettings.for_database("AdventureWorksLT2019")
            # Creates collections: "table_schemas_AdventureWorksLT2019" and "view_schemas_AdventureWorksLT2019"
        """
        return cls(
            persist_directory=persist_dir,
            schema_collection=f"table_schemas_{database_name}",
            views_collection=f"view_schemas_{database_name}",
        )


# Singleton default settings — override per environment
DEFAULT_SETTINGS = VectorSettings()

__all__ = ["VectorSettings", "DEFAULT_SETTINGS"]
