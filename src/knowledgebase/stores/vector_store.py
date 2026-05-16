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

    Two collections per database (named dynamically):
    - {database_name}__schemas  : for table/schema documents
    - {database_name}__views    : for view documents
    """

    def __init__(self, settings: VectorSettings = DEFAULT_SETTINGS):
        self._settings = settings
        self._embedding_fn = ONNXMiniLM_L6_V2()

        self._client = chromadb.PersistentClient(
            path=settings.persist_directory,
            settings=Settings(anonymized_telemetry=False),
        )

        logger.info(
            "✅ VectorStore ready — persist_directory: %s", settings.persist_directory
        )

    # ------------------------------------------------------------------ #
    #  Collection Resolver                                                 #
    # ------------------------------------------------------------------ #

    def _schema_col(self, database_name: str):
        """Get or create schema collection scoped to a database."""
        return self._client.get_or_create_collection(
            name=f"{database_name}__schemas",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    def _views_col(self, database_name: str):
        """Get or create views collection scoped to a database."""
        return self._client.get_or_create_collection(
            name=f"{database_name}__views",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------ #
    #  Upsert                                                              #
    # ------------------------------------------------------------------ #

    def upsert_schemas(
        self,
        database_name: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Upsert table schema documents into the database-scoped schema collection."""
        if not ids:
            logger.warning("No schema documents to upsert")
            return

        try:
            self._schema_col(database_name).upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.info(
                "✅ Upserted %d schema docs into '%s__schemas'", len(ids), database_name
            )
        except Exception as exc:
            logger.error("❌ Failed to upsert schema documents: %s", exc)
            raise

    def upsert_views(
        self,
        database_name: str,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Upsert view documents into the database-scoped views collection."""
        if not ids:
            logger.warning("No view documents to upsert")
            return

        try:
            self._views_col(database_name).upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            logger.info(
                "✅ Upserted %d view docs into '%s__views'", len(ids), database_name
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
        database_name: str,
        top_k: Optional[int] = None,
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query schema collection scoped to a database."""
        if not database_name:
            raise ValueError("database_name is required")

        where_clause = self._build_where_clause(
            schema_name=schema_name,
            table_name=table_name,
        )

        return self._query_collection(
            self._schema_col(database_name),
            embedding,
            top_k or self._settings.top_k,
            where=where_clause,
        )

    def query_views(
        self,
        embedding: list[float],
        database_name: str,
        top_k: Optional[int] = None,
        schema_name: Optional[str] = None,
        view_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query views collection scoped to a database."""
        if not database_name:
            raise ValueError("database_name is required")

        where_clause = self._build_where_clause(
            schema_name=schema_name,
            view_name=view_name,
        )

        return self._query_collection(
            self._views_col(database_name),
            embedding,
            top_k or self._settings.top_k,
            where=where_clause,
        )

    def query_all(
        self,
        embedding: list[float],
        database_name: str,
        top_k: Optional[int] = None,
        schema_name: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Query both collections for a database and return merged results sorted by distance."""
        if not database_name:
            raise ValueError("database_name is required")

        top_k = top_k or self._settings.top_k
        where_clause = self._build_where_clause(schema_name=schema_name)

        schema_results = self._query_collection(
            self._schema_col(database_name), embedding, top_k, where=where_clause
        )
        view_results = self._query_collection(
            self._views_col(database_name), embedding, top_k, where=where_clause
        )

        merged = schema_results + view_results
        merged.sort(key=lambda x: x.get("distance", float("inf")))
        return merged[:top_k]

    # ------------------------------------------------------------------ #
    #  Housekeeping                                                        #
    # ------------------------------------------------------------------ #

    def clear_schemas(self, database_name: str) -> None:
        """Wipe and recreate the schema collection for a database."""
        try:
            self._client.delete_collection(f"{database_name}__schemas")
            logger.info("🗑️  Schema collection cleared for '%s'", database_name)
        except Exception as exc:
            error_msg = str(exc)
            if "does not exist" in error_msg:
                logger.warning(
                    "Schema collection does not exist for '%s'", database_name
                )
            else:
                logger.error("❌ Failed to clear schema collection: %s", exc)
            raise

    def clear_views(self, database_name: str) -> None:
        """Wipe and recreate the views collection for a database."""
        try:
            self._client.delete_collection(f"{database_name}__views")
            logger.info("🗑️  Views collection cleared for '%s'", database_name)
        except Exception as exc:
            error_msg = str(exc)
            if "does not exist" in error_msg:
                logger.warning(
                    "Views collection does not exist for '%s'", database_name
                )
            else:
                logger.error("❌ Failed to clear views collection: %s", exc)
            raise

    def delete_database(self, database_name: str) -> dict[str, int]:
        """Drop both schema and views collections for a database entirely."""
        schema_count = self._schema_col(database_name).count()
        views_count = self._views_col(database_name).count()

        self.clear_schemas(database_name)
        self.clear_views(database_name)

        logger.info("🗑️  All collections dropped for '%s'", database_name)
        return {"schemas_deleted": schema_count, "views_deleted": views_count}

    def list_databases(self) -> dict[str, set[str]]:
        """
        Return all database names with their collection types.

        Returns:
            dict mapping database_name -> set of collection types ("schemas", "views")

        Example:
            {"AdventureWorksLT2019": {"schemas", "views"}, "OtherDB": {"schemas"}}
        """
        collections = self._client.list_collections()
        databases: dict[str, set[str]] = {}
        logger.info("🗑️  All collections database '%s'", collections)
        for col in collections:
            if "__schemas" in col.name:
                db_name = col.name.rsplit("__", 1)[0]
                if db_name not in databases:
                    databases[db_name] = set()
                databases[db_name].add("schemas")
            elif "__views" in col.name:
                db_name = col.name.rsplit("__", 1)[0]
                if db_name not in databases:
                    databases[db_name] = set()
                databases[db_name].add("views")
        return dict(sorted(databases.items()))

    def stats(self, database_name: str) -> dict[str, Any]:
        """Return statistics for a specific database's collections."""
        schema_col = self._schema_col(database_name)
        views_col = self._views_col(database_name)
        schema_count = schema_col.count()
        views_count = views_col.count()

        return {
            "database_name": database_name,
            "schema_collection": {
                "name": f"{database_name}__schemas",
                "document_count": schema_count,
            },
            "views_collection": {
                "name": f"{database_name}__views",
                "document_count": views_count,
            },
            "persist_directory": self._settings.persist_directory,
            "total_documents": schema_count + views_count,
        }

    # ------------------------------------------------------------------ #
    #  Internal Helpers                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_where_clause(
        schema_name: Optional[str] = None,
        table_name: Optional[str] = None,
        view_name: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Build a ChromaDB where clause from optional filter parameters.
        database_name is no longer needed — collections are already scoped per DB.
        """
        conditions = []

        if schema_name:
            conditions.append({"schema_name": schema_name})
        if table_name:
            conditions.append({"table_name": table_name})
        if view_name:
            conditions.append({"view_name": view_name})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    @staticmethod
    def _query_collection(
        collection: Any,
        embedding: list[float],
        top_k: int,
        where: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Query a single collection and format results."""
        if collection.count() == 0:
            return []

        try:
            query_kwargs = {
                "query_embeddings": [embedding],
                "n_results": min(top_k, collection.count()),
                "include": ["documents", "metadatas", "distances"],
            }
            if where:
                query_kwargs["where"] = where

            results = collection.query(**query_kwargs)
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
