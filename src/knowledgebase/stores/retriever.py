import logging
from enum import Enum
from typing import Optional

from pydantic import BaseModel

from .config import VectorSettings, DEFAULT_SETTINGS
from .embedder import Embedder
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


class SearchTarget(str, Enum):
    SCHEMAS = "schemas"
    VIEWS = "views"
    ALL = "all"


class RetrievalResult(BaseModel):
    document: str
    metadata: dict
    distance: float
    source_type: str  # "table" or "view"


class Retriever:
    """
    Semantic search over indexed schemas and views.
    Returns the top-k most relevant documents for a natural language query.

    Usage:
        retriever = Retriever()
        results = retriever.search("which table stores customer orders?")
        context = retriever.get_rag_context("show me revenue by product")
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

    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        target: SearchTarget = SearchTarget.ALL,
    ) -> list[RetrievalResult]:
        """
        Embed the query and return top-k semantically similar schema/view docs.

        Args:
            query:  Natural language question or keyword string.
            top_k:  Number of results to return (defaults to settings.top_k).
            target: Search only schemas, only views, or both.

        Returns:
            List of RetrievalResult sorted by relevance (lowest distance first).
        """
        k = top_k or self._settings.top_k
        embedding = self._embedder.embed(query)

        if target == SearchTarget.SCHEMAS:
            raw = self._store.query_schemas(embedding, k)
        elif target == SearchTarget.VIEWS:
            raw = self._store.query_views(embedding, k)
        else:
            raw = self._store.query_all(embedding, k)

        results = [
            RetrievalResult(
                document=r["document"],
                metadata=r["metadata"],
                distance=r["distance"],
                source_type=r["metadata"].get("type", "unknown"),
            )
            for r in raw
        ]

        logger.info(
            "🔍 Query: '%s' → %d results (target=%s)", query, len(results), target
        )
        return results

    def get_rag_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        target: SearchTarget = SearchTarget.ALL,
    ) -> str:
        """
        Returns a single formatted string ready to inject into an LLM prompt.

        Example output injected into a system prompt:
            ### Relevant Database Context ###

            [Table] public.orders
            Table: public.orders
            Description: Stores customer orders
            Columns:
              - id (INTEGER) [Primary Key]
              ...

            [View] dbo.active_customers
            View: dbo.active_customers
            ...
        """
        results = self.search(query, top_k=top_k, target=target)

        if not results:
            return "No relevant schema or view context found."

        sections = ["### Relevant Database Context ###\n"]
        for r in results:
            label = (
                f"[Table] {r.metadata.get('schema_name')}.{r.metadata.get('table_name')}"
                if r.source_type == "table"
                else f"[View] {r.metadata.get('schema_name')}.{r.metadata.get('view_name')}"
            )
            sections.append(f"{label}\n{r.document}\n")

        return "\n".join(sections)

    def stats(self) -> dict:
        return self._store.stats()


__all__ = ["Retriever", "RetrievalResult", "SearchTarget"]
