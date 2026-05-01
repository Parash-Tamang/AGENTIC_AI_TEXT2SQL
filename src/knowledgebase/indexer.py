import logging
from typing import Optional

from ..service.schema_service import TableSchema
from ..service.view_service import ViewSchema
from .config import VectorSettings, DEFAULT_SETTINGS
from .embedder import Embedder
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


class Indexer:
    """
    Converts TableSchema / ViewSchema objects into text documents,
    embeds them with sentence-transformers, and upserts into ChromaDB.

    Usage:
        indexer = Indexer()
        indexer.index_schemas(schema_service.get_schema(engine))
        indexer.index_views(view_service.get_views(engine))
    """

    def __init__(
        self,
        settings: VectorSettings = DEFAULT_SETTINGS,
        embedder: Optional[Embedder] = None,
        store: Optional[VectorStore] = None,
    ):
        self._settings = settings
        self._embedder = embedder or Embedder(settings)
        self._store = store or VectorStore(settings)

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def index_schemas(self, tables: list[TableSchema]) -> int:
        """Embed and store all TableSchema objects. Returns count indexed."""
        if not tables:
            logger.warning("⚠️  No tables provided to index_schemas")
            return 0

        ids, documents, metadatas = [], [], []

        for table in tables:
            doc_id = f"{table.database_name}.{table.schema_name}.{table.table_name}"
            document = self._format_table(table)
            ids.append(doc_id)
            documents.append(document)
            metadatas.append(
                {
                    "database_name": table.database_name,
                    "schema_name": table.schema_name,
                    "table_name": table.table_name,
                    "type": "table",
                }
            )

        embeddings = self._embedder.embed_batch(documents)
        self._store.upsert_schemas(ids, documents, embeddings, metadatas)
        logger.info("✅ Indexed %d table schemas", len(ids))
        return len(ids)

    def index_views(self, views: list[ViewSchema]) -> int:
        """Embed and store all ViewSchema objects. Returns count indexed."""
        if not views:
            logger.warning("⚠️  No views provided to index_views")
            return 0

        ids, documents, metadatas = [], [], []

        for view in views:
            doc_id = f"{view.database_name}.{view.schema_name}.{view.view_name}"
            document = self._format_view(view)
            ids.append(doc_id)
            documents.append(document)
            metadatas.append(
                {
                    "database_name": view.database_name,
                    "schema_name": view.schema_name,
                    "view_name": view.view_name,
                    "type": "view",
                }
            )

        embeddings = self._embedder.embed_batch(documents)
        self._store.upsert_views(ids, documents, embeddings, metadatas)
        logger.info("✅ Indexed %d views", len(ids))
        return len(ids)

    def index_all(
        self,
        tables: list[TableSchema],
        views: list[ViewSchema],
    ) -> dict:
        """Convenience method to index both in one call."""
        return {
            "tables_indexed": self.index_schemas(tables),
            "views_indexed": self.index_views(views),
        }

    # ------------------------------------------------------------------ #
    #  Text Formatters                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_table(table: TableSchema) -> str:
        """
        Produces a rich natural-language description of a table.

        Example output:
            Table: public.orders
            Description: Stores customer orders
            Columns:
              - id (INTEGER) [Primary Key]
              - customer_id (INTEGER) [Foreign Key → customers.id]
              - status (VARCHAR) [not null] | Samples: pending, shipped, delivered
        """
        lines = [
            f"Table: {table.schema_name}.{table.table_name}",
        ]
        if table.table_description:
            lines.append(f"Description: {table.table_description}")

        lines.append("Columns:")
        for col in table.columns:
            col_line = f"  - {col.name} ({col.type}) [{col.constraint}]"
            if col.relation:
                col_line += f" → {col.relation}"
            if col.description:
                col_line += f" | Info: {col.description}"
            if col.sample_values:
                samples = ", ".join(col.sample_values[:3])
                col_line += f" | Samples: {samples}"
            lines.append(col_line)

        return "\n".join(lines)

    @staticmethod
    def _format_view(view: ViewSchema) -> str:
        """
        Produces a rich natural-language description of a view.

        Example output:
            View: dbo.active_customers
            Description: Customers with active subscriptions
            Columns:
              - customer_id (INT)
              - full_name (NVARCHAR)
            Definition: SELECT c.id, c.name FROM customers c WHERE c.active = 1
        """
        lines = [
            f"View: {view.schema_name}.{view.view_name}",
        ]
        if view.view_description:
            lines.append(f"Description: {view.view_description}")

        lines.append("Columns:")
        for col in view.columns:
            col_line = f"  - {col.name} ({col.type})"
            if col.description:
                col_line += f" | Info: {col.description}"
            lines.append(col_line)

        if view.view_definition:
            # Truncate very long definitions to keep the doc focused
            definition = view.view_definition.strip()
            if len(definition) > 800:
                definition = definition[:800] + "..."
            lines.append(f"Definition:\n{definition}")

        return "\n".join(lines)


__all__ = ["Indexer"]
