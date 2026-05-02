import logging
from typing import Any, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

from src.knowledgebase.config.vector_setting import VectorSettings, DEFAULT_SETTINGS

logger = logging.getLogger(__name__)


class VectorStore:
    """
    Manages ChromaDB collections for table schemas and views.
    Uses persistent local storage and ONNX embeddings for efficient, CPU-based retrieval.

    Two collections per database:
    - schema_collection: for table/schema documents
    - views_collection: for view documents
    """

    def __init__(self, settings: VectorSettings = DEFAULT_SETTINGS):
        self._settings = settings
        self._embedding_fn = ONNXMiniLM_L6_V2()

        self._client = chromadb.PersistentClient(
            path=settings.persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )

        self._schema_col = self._client.get_or_create_collection(
            name=settings.schema_collection,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

        self._views_col = self._client.get_or_create_collection(
            name=settings.views_collection,
            embedding_function=self._embedding_fn,
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
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Upsert table schema documents into the schema collection."""
        if not ids:
            logger.warning("No schema documents to upsert")
            return

        try:
            self._schema_col.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.info(
                "✅ Upserted %d schema documents into '%s'",
                len(ids),
                self._settings.schema_collection,
            )
        except Exception as exc:
            logger.error("❌ Failed to upsert schema documents: %s", exc)
            raise

    def upsert_views(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Upsert view documents into the views collection."""
        if not ids:
            logger.warning("No view documents to upsert")
            return

        try:
            self._views_col.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.info(
                "✅ Upserted %d view documents into '%s'",
                len(ids),
                self._settings.views_collection,
            )
        except Exception as exc:
            logger.error("❌ Failed to upsert view documents: %s", exc)
            raise

    # ------------------------------------------------------------------ #
    #  Query                                                               #
    # ------------------------------------------------------------------ #

    def query_schemas(
        self,
        embedding: list[float],
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Query schema collection by embedding."""
        if top_k is None:
            top_k = self._settings.top_k
        return self._query_collection(self._schema_col, embedding, top_k)

    def query_views(
        self,
        embedding: list[float],
        top_k: Optional[int] = None,
        database: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query views collection by embedding."""
        if top_k is None:
            top_k = self._settings.top_k
        return self._query_collection(
            self._views_col, embedding, top_k, database=database
        )

    def query_all(
        self,
        embedding: list[float],
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Query both collections and return merged results sorted by distance."""
        if top_k is None:
            top_k = self._settings.top_k

        schema_results = self._query_collection(self._schema_col, embedding, top_k)
        view_results = self._query_collection(self._views_col, embedding, top_k)

        merged = schema_results + view_results
        merged.sort(key=lambda x: x.get("distance", float("inf")))
        return merged[:top_k]

    # ------------------------------------------------------------------ #
    #  Housekeeping                                                        #
    # ------------------------------------------------------------------ #

    def clear_schemas(self) -> None:
        """Delete and recreate the schema collection."""
        try:
            self._client.delete_collection(self._settings.schema_collection)
            # self._schema_col = self._client.get_or_create_collection(
            #     name=self._settings.schema_collection,
            #     embedding_function=self._embedding_fn,
            #     metadata={"hnsw:space": "cosine"},
            # )
            logger.info("🗑️  Schema collection cleared")
        except Exception as exc:
            logger.error("❌ Failed to clear schema collection: %s", exc)
            raise

    def clear_views(self) -> None:
        """Delete and recreate the views collection."""
        try:
            self._client.delete_collection(self._settings.views_collection)
            # self._views_col = self._client.get_or_create_collection(
            #     name=self._settings.views_collection,
            #     embedding_function=self._embedding_fn,
            #     metadata={"hnsw:space": "cosine"},
            # )
            logger.info("🗑️  Views collection cleared")
        except Exception as exc:
            logger.error("❌ Failed to clear views collection: %s", exc)
            raise

    def stats(self) -> dict[str, Any]:
        """Return statistics about both collections."""
        return {
            "schema_collection": {
                "name": self._settings.schema_collection,
                "document_count": self._schema_col.count(),
            },
            "views_collection": {
                "name": self._settings.views_collection,
                "document_count": self._views_col.count(),
            },
            "persist_directory": self._settings.persist_directory,
            "total_documents": self._schema_col.count() + self._views_col.count(),
        }

    # ------------------------------------------------------------------ #
    #  Internal Helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _query_collection(
        collection: Any,
        embedding: list[float],
        top_k: int,
        database: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query a single collection and format results."""
        if collection.count() == 0:
            return []

        try:
            results = collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k, collection.count()),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            logger.error("❌ Query failed: %s", exc)
            return []

        output = []
        if results and results.get("documents"):
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                output.append(
                    {
                        "document": doc,
                        "metadata": meta,
                        "distance": float(dist),
                    }
                )

        return output


__all__ = ["VectorStore"]
