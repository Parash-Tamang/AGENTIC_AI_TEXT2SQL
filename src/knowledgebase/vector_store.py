import logging

import chromadb
from chromadb.config import Settings

from .config import VectorSettings, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Manages ChromaDB collections for table schemas and views.
    Uses persistent local storage so embeddings survive restarts.
    """

    def __init__(self, settings: VectorSettings = DEFAULT_SETTINGS):
        self._settings = settings
        self._client = chromadb.PersistentClient(
            path=settings.persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self._schema_col = self._client.get_or_create_collection(
            name=settings.schema_collection,
            metadata={"hnsw:space": "cosine"},
        )
        self._views_col = self._client.get_or_create_collection(
            name=settings.views_collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "✅ VectorStore ready — schema docs: %d | view docs: %d",
            self._schema_col.count(),
            self._views_col.count(),
        )

    # ------------------------------------------------------------------ #
    #  Upsert                                                              #
    # ------------------------------------------------------------------ #

    def upsert_schemas(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        self._schema_col.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.info("✅ Upserted %d schema documents", len(ids))

    def upsert_views(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict],
    ) -> None:
        self._views_col.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.info("✅ Upserted %d view documents", len(ids))

    # ------------------------------------------------------------------ #
    #  Query                                                               #
    # ------------------------------------------------------------------ #

    def query_schemas(self, embedding: list[float], top_k: int) -> list[dict]:
        return self._query(self._schema_col, embedding, top_k)

    def query_views(self, embedding: list[float], top_k: int) -> list[dict]:
        return self._query(self._views_col, embedding, top_k)

    def query_all(self, embedding: list[float], top_k: int) -> list[dict]:
        """Query both collections and return merged results sorted by distance."""
        schema_results = self._query(self._schema_col, embedding, top_k)
        view_results = self._query(self._views_col, embedding, top_k)
        merged = schema_results + view_results
        merged.sort(key=lambda x: x["distance"])
        return merged[:top_k]

    # ------------------------------------------------------------------ #
    #  Housekeeping                                                        #
    # ------------------------------------------------------------------ #

    def clear_schemas(self) -> None:
        self._client.delete_collection(self._settings.schema_collection)
        self._schema_col = self._client.get_or_create_collection(
            name=self._settings.schema_collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("🗑️  Schema collection cleared")

    def clear_views(self) -> None:
        self._client.delete_collection(self._settings.views_collection)
        self._views_col = self._client.get_or_create_collection(
            name=self._settings.views_collection,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("🗑️  Views collection cleared")

    def stats(self) -> dict:
        return {
            "schema_docs": self._schema_col.count(),
            "view_docs": self._views_col.count(),
            "persist_directory": self._settings.persist_directory,
        }

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _query(collection, embedding: list[float], top_k: int) -> list[dict]:
        if collection.count() == 0:
            return []
        results = collection.query(
            query_embeddings=[embedding],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )
        output = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            output.append({"document": doc, "metadata": meta, "distance": dist})
        return output


__all__ = ["VectorStore"]
