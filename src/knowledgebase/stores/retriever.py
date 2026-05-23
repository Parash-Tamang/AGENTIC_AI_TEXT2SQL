"""
retriever.py
────────────
Smart semantic retrieval built on top of VectorStore.query_schemas /
query_views — all database / schema / table / view filters are handled
by VectorStore, not raw ChromaDB calls.

Public surface
──────────────
    retrieve_schemas(queries, store, embedder, database_name, ...)
    retrieve_views(queries, store, embedder, database_name, ...)
    retrieve_all(queries, store, embedder, database_name, ...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from .embedder import Embedder
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

_DEFAULT_BASE_THRESHOLD = 0.55
_DEFAULT_MAX_THRESHOLD = 0.70
_THRESHOLD_STEP = 0.05


# ── Result model ──────────────────────────────────────────────────────────────


@dataclass
class RetrievedChunk:
    doc: str
    dist: float
    meta: dict[str, Any]
    source_query: str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _run_retrieval(
    queries: list[str],
    embedder: Embedder,
    fetch_fn,  # store.query_schemas or store.query_views
    base_threshold: float,
    max_threshold: float,
    min_results: int,
    max_results: int,
    n_per_query: int,
) -> list[RetrievedChunk]:
    """
    Core retrieval loop shared by retrieve_schemas / retrieve_views / retrieve_all.

    For each query:
      1. Embed the query text.
      2. Call fetch_fn (already bound with all filters).
      3. Filter results by cosine distance threshold.
      4. Expand threshold if min_results not yet reached.
      5. Deduplicate globally by doc_id and cap at max_results.
    """
    seen_ids: set[str] = set()
    chunks: list[RetrievedChunk] = []

    for query in queries:
        if len(chunks) >= max_results:
            break

        embedding = embedder.embed(query)
        threshold = base_threshold

        while threshold <= max_threshold + 0.2:
            if len(chunks) >= max_results:
                break

            candidates = fetch_fn(embedding=embedding, top_k=n_per_query)

            logger.debug(
                "query=%r threshold=%.2f candidates=%d total=%d",
                query,
                threshold,
                len(candidates),
                len(chunks),
            )

            for item in candidates:
                if item["distance"] > threshold:
                    continue
                item_id = item["metadata"].get("table_name") or item["metadata"].get(
                    "view_name"
                )
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                chunks.append(
                    RetrievedChunk(
                        doc=item["document"],
                        dist=item["distance"],
                        meta=item["metadata"],
                        source_query=query,
                    )
                )
                if len(chunks) >= max_results:
                    break

            if len(chunks) >= min_results:
                break

            threshold = round(threshold + _THRESHOLD_STEP, 10)

    chunks.sort(key=lambda c: c.dist)
    return chunks


# ── Public API ────────────────────────────────────────────────────────────────


def retrieve_schemas(
    queries: list[str],
    store: VectorStore,
    embedder: Embedder,
    database_name: str,
    schema_name: Optional[str] = None,
    table_name: Optional[str] = None,
    base_threshold: float = _DEFAULT_BASE_THRESHOLD,
    max_threshold: float = _DEFAULT_MAX_THRESHOLD,
    min_results: int = 5,
    max_results: int = 10,
    n_per_query: int = 5,
) -> list[RetrievedChunk]:
    """
    Smart retrieval from the schema (tables) collection.

    Filter combos
    -------------
    database_name only               → all tables in that database
    database_name + schema_name      → all tables in that db.schema
    database_name + table_name       → specific table in that database

    Parameters
    ----------
    queries:
        List of query strings (e.g. entity-based subqueries from upstream).
    store:
        VectorStore instance — owns the ChromaDB collections.
    embedder:
        Embedder instance — converts query strings to vectors.
    database_name:
        Required. Scopes all queries to this database.
    """
    if not database_name:
        raise ValueError("database_name is required")
    if not queries:
        logger.warning("retrieve_schemas called with empty queries list")
        return []

    fetch_fn = lambda embedding, top_k: store.query_schemas(
        embedding=embedding,
        top_k=top_k,
        database_name=database_name,
        schema_name=schema_name,
        table_name=table_name,
    )

    return _run_retrieval(
        queries=queries,
        embedder=embedder,
        fetch_fn=fetch_fn,
        base_threshold=base_threshold,
        max_threshold=max_threshold,
        min_results=min_results,
        max_results=max_results,
        n_per_query=n_per_query,
    )


def retrieve_views(
    queries: list[str],
    store: VectorStore,
    embedder: Embedder,
    database_name: str,
    schema_name: Optional[str] = None,
    view_name: Optional[str] = None,
    base_threshold: float = _DEFAULT_BASE_THRESHOLD,
    max_threshold: float = _DEFAULT_MAX_THRESHOLD,
    min_results: int = 5,
    max_results: int = 10,
    n_per_query: int = 5,
) -> list[RetrievedChunk]:
    """
    Smart retrieval from the views collection.

    Filter combos
    -------------
    database_name only               → all views in that database
    database_name + schema_name      → all views in that db.schema
    database_name + view_name        → specific view in that database
    """
    if not database_name:
        raise ValueError("database_name is required")
    if not queries:
        logger.warning("retrieve_views called with empty queries list")
        return []

    fetch_fn = lambda embedding, top_k: store.query_views(
        embedding=embedding,
        top_k=top_k,
        database_name=database_name,
        schema_name=schema_name,
        view_name=view_name,
    )

    return _run_retrieval(
        queries=queries,
        embedder=embedder,
        fetch_fn=fetch_fn,
        base_threshold=base_threshold,
        max_threshold=max_threshold,
        min_results=min_results,
        max_results=max_results,
        n_per_query=n_per_query,
    )


def retrieve_all(
    queries: list[str],
    store: VectorStore,
    embedder: Embedder,
    database_name: str,
    schema_name: Optional[str] = None,
    base_threshold: float = _DEFAULT_BASE_THRESHOLD,
    max_threshold: float = _DEFAULT_MAX_THRESHOLD,
    min_results: int = 5,
    max_results: int = 10,
    n_per_query: int = 5,
) -> list[RetrievedChunk]:
    """
    Smart retrieval across both schemas and views, merged and sorted by distance.

    Filter combos
    -------------
    database_name only               → all tables + views in that database
    database_name + schema_name      → all tables + views in that db.schema
    """
    if not database_name:
        raise ValueError("database_name is required")
    if not queries:
        logger.warning("retrieve_all called with empty queries list")
        return []

    fetch_fn = lambda embedding, top_k: store.query_all(
        embedding=embedding,
        top_k=top_k,
        database_name=database_name,
        schema_name=schema_name,
    )

    return _run_retrieval(
        queries=queries,
        embedder=embedder,
        fetch_fn=fetch_fn,
        base_threshold=base_threshold,
        max_threshold=max_threshold,
        min_results=min_results,
        max_results=max_results,
        n_per_query=n_per_query,
    )


__all__ = ["retrieve_schemas", "retrieve_views", "retrieve_all", "RetrievedChunk"]
