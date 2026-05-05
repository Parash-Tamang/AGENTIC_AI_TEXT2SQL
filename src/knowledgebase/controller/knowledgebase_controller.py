"""
knowledgebase_router.py
───────────────────────
FastAPI controller for managing vector knowledge base collections.
All data is generated directly from a live database connection.

Endpoints
─────────
    GET    /knowledgebase/list                              → list all indexed databases
    GET    /knowledgebase/{database_name}/stats             → collection stats

    POST   /knowledgebase/{database_name}/schemas/create   → generate from DB + index schemas
    POST   /knowledgebase/{database_name}/views/create     → generate from DB + index views
    PUT    /knowledgebase/{database_name}/schemas/update   → wipe + regenerate schemas from DB
    PUT    /knowledgebase/{database_name}/views/update     → wipe + regenerate views from DB
    DELETE /knowledgebase/{database_name}/schemas/delete   → wipe schema collection
    DELETE /knowledgebase/{database_name}/views/delete     → wipe views collection
    DELETE /knowledgebase/{database_name}/delete           → wipe both collections
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Optional, Generic, TypeVar, Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

T = TypeVar("T")

from src.database.executor import generate_schema, generate_views
from src.database.service.schema_service import SchemaService, ExclusionConfig
from src.database.service.view_service import ViewService
from src.knowledgebase.stores.indexer import Indexer
from src.knowledgebase.stores.vector_store import VectorStore
from src.knowledgebase.graph.build_ import build_schema_graph
from src.knowledgebase.config.graph_setting import GraphSettings, DEFAULT_GRAPH_SETTINGS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledgebase", tags=["knowledgebase"])


# ── Request models ────────────────────────────────────────────────────────────


class DBConnectionRequest(BaseModel):
    db_type: str = "mssql"
    server: str
    username: Optional[str] = None
    password: Optional[str] = None
    timeout: int = 30
    excluded_schemas: list[str] = []
    excluded_tables: list[str] = []
    excluded_columns: list[str] = []


# ── Generic Response Wrapper ──────────────────────────────────────────────────────


class ApiResponse(BaseModel, Generic[T]):
    """Unified API response envelope with success, message, and data."""

    success: bool
    message: str
    data: Optional[T] = None


# ── Response models ───────────────────────────────────────────────────────────


class IndexResponse(BaseModel):
    database_name: str
    schema_type: str
    indexed: int
    message: str


class DeleteResponse(BaseModel):
    database_name: str
    deleted: list[str]
    message: str


class StatsResponse(BaseModel):
    database_name: str
    schema_collection: dict
    views_collection: dict
    total_documents: int
    persist_directory: str


class ListDatabasesResponse(BaseModel):
    databases: dict[str, list[str]]
    total: int


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_exclusions(req: DBConnectionRequest) -> Optional[ExclusionConfig]:
    if req.excluded_schemas or req.excluded_tables or req.excluded_columns:
        return ExclusionConfig(
            schemas=req.excluded_schemas,
            tables=req.excluded_tables,
            columns=req.excluded_columns,
        )
    return None


def _build_schema_graphs(
    database_name: str,
    schema_file: str,
    settings: GraphSettings = DEFAULT_GRAPH_SETTINGS,
) -> str:
    """Build schema graph from schema JSON file."""
    try:
        graph_path = build_schema_graph(
            schema_file, database_name, settings.persist_directory
        )
        logger.info("✅ Schema graph built for '%s' → %s", database_name, graph_path)
        return graph_path
    except Exception as exc:
        logger.error("❌ Failed to build schema graph for '%s': %s", database_name, exc)
        raise


def _delete_schema_graphs(
    database_name: str, settings: GraphSettings = DEFAULT_GRAPH_SETTINGS
) -> None:
    """Delete schema graph for a database."""
    try:
        graph_dir = os.path.join(settings.persist_directory, database_name.lower())
        if os.path.exists(graph_dir):
            shutil.rmtree(graph_dir)
            logger.info("🗑️  Schema graph deleted for '%s'", database_name)
    except Exception as exc:
        logger.error(
            "❌ Failed to delete schema graph for '%s': %s", database_name, exc
        )
        raise


def _generate_schema(database_name: str, req: DBConnectionRequest):
    """Generate schema from DB and raise 500/404 on failure."""
    try:
        schema = generate_schema(
            db_type=req.db_type,
            server=req.server,
            database=database_name,
            username=req.username,
            password=req.password,
            timeout=req.timeout,
            exclusions=_build_exclusions(req),
        )
    except Exception as exc:
        logger.error("DB connection failed for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DB connection failed: {exc}",
        )
    if not schema:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No schema found for '{database_name}'",
        )
    return schema


def _generate_views(database_name: str, req: DBConnectionRequest):
    """Generate views from DB and raise 500/404 on failure."""
    try:
        views = generate_views(
            db_type=req.db_type,
            server=req.server,
            database=database_name,
            username=req.username,
            password=req.password,
            timeout=req.timeout,
        )
    except Exception as exc:
        logger.error("DB connection failed for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DB connection failed: {exc}",
        )
    if not views:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No views found for '{database_name}'",
        )
    return views


# ── LIST ──────────────────────────────────────────────────────────────────────


@router.get(
    "/list",
    response_model=ApiResponse[ListDatabasesResponse],
    summary="List all indexed databases",
)
def list_databases() -> ApiResponse[ListDatabasesResponse]:
    """Return all databases that have indexed collections."""
    try:
        databases_dict = VectorStore().list_databases()
        # Convert sets to lists for JSON serialization
        databases = {db: sorted(list(types)) for db, types in databases_dict.items()}
        data = ListDatabasesResponse(databases=databases, total=len(databases))
        return ApiResponse(
            success=True, message="Databases retrieved successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to list databases: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ── STATS ─────────────────────────────────────────────────────────────────────


@router.get(
    "/{database_name}/stats",
    response_model=ApiResponse[StatsResponse],
    summary="Get collection stats for a database",
)
def get_stats(database_name: str) -> ApiResponse[StatsResponse]:
    """Return document counts and metadata for both collections."""
    try:
        stats = VectorStore().stats(database_name)
        data = StatsResponse(**stats)
        return ApiResponse(
            success=True, message="Stats retrieved successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to get stats for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ── CREATE ────────────────────────────────────────────────────────────────────


@router.post(
    "/{database_name}/schemas/create",
    response_model=ApiResponse[IndexResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate schema from live DB and index it",
)
def create_schemas(
    database_name: str, req: DBConnectionRequest
) -> ApiResponse[IndexResponse]:
    """Connect to the database, generate schema, save snapshot, and index (additive)."""
    # Check if schemas already exist
    existing_dbs = VectorStore().list_databases()
    if database_name in existing_dbs and "schemas" in existing_dbs[database_name]:
        logger.warning(
            "Schemas already exist for '%s', skipping creation", database_name
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Schemas already indexed for '{database_name}'. Use PUT /schemas/update to regenerate.",
        )

    schema = _generate_schema(database_name, req)

    try:
        schema_file = SchemaService.save_schema_snapshot(schema)
        count = Indexer().index_schemas(database_name, schema)
        # Build schema graph after indexing
        _build_schema_graphs(database_name, str(schema_file))
        data = IndexResponse(
            database_name=database_name,
            schema_type="table",
            indexed=count,
            message=f"Generated and indexed {count} table schemas for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Schemas created and indexed successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to index schemas for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.post(
    "/{database_name}/views/create",
    response_model=ApiResponse[IndexResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate views from live DB and index them",
)
def create_views(
    database_name: str, req: DBConnectionRequest
) -> ApiResponse[IndexResponse]:
    """Connect to the database, generate views, save snapshot, and index (additive)."""
    # Check if views already exist
    existing_dbs = VectorStore().list_databases()
    if database_name in existing_dbs and "views" in existing_dbs[database_name]:
        logger.warning("Views already exist for '%s', skipping creation", database_name)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Views already indexed for '{database_name}'. Use PUT /views/update to regenerate.",
        )

    views = _generate_views(database_name, req)

    try:
        ViewService.save_views_snapshot(views)
        count = Indexer().index_views(database_name, views)
        data = IndexResponse(
            database_name=database_name,
            schema_type="view",
            indexed=count,
            message=f"Generated and indexed {count} views for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Views created and indexed successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to index views for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ── UPDATE (wipe + regenerate) ────────────────────────────────────────────────


@router.put(
    "/{database_name}/schemas/update",
    response_model=ApiResponse[IndexResponse],
    summary="Wipe and regenerate table schemas from live DB",
)
def update_schemas(
    database_name: str, req: DBConnectionRequest
) -> ApiResponse[IndexResponse]:
    """Wipe schema collection, reconnect to DB, regenerate and reindex. Removes ghost tables."""
    schema = _generate_schema(database_name, req)

    try:
        schema_file = SchemaService.save_schema_snapshot(schema)
        count = Indexer().update_schemas(database_name, schema)
        # Rebuild schema graph after updating
        _build_schema_graphs(database_name, str(schema_file))
        data = IndexResponse(
            database_name=database_name,
            schema_type="table",
            indexed=count,
            message=f"Wiped and reindexed {count} table schemas for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Schemas updated successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to update schemas for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.put(
    "/{database_name}/views/update",
    response_model=ApiResponse[IndexResponse],
    summary="Wipe and regenerate views from live DB",
)
def update_views(
    database_name: str, req: DBConnectionRequest
) -> ApiResponse[IndexResponse]:
    """Wipe views collection, reconnect to DB, regenerate and reindex. Removes ghost views."""
    views = _generate_views(database_name, req)

    try:
        ViewService.save_views_snapshot(views)
        count = Indexer().update_views(database_name, views)
        data = IndexResponse(
            database_name=database_name,
            schema_type="view",
            indexed=count,
            message=f"Wiped and reindexed {count} views for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Views updated successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to update views for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


# ── DELETE ────────────────────────────────────────────────────────────────────


@router.delete(
    "/{database_name}/schemas/delete",
    response_model=ApiResponse[DeleteResponse],
    summary="Wipe schema collection for a database",
)
def delete_schemas(database_name: str) -> ApiResponse[DeleteResponse]:
    """Delete the schema collection and graph for a database (all data wiped)."""
    try:
        VectorStore().clear_schemas(database_name)
        # Delete schema graph too
        _delete_schema_graphs(database_name)
        data = DeleteResponse(
            database_name=database_name,
            deleted=["schemas", "schema_graph"],
            message=f"Schema collection and graph wiped for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Schemas deleted successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to delete schemas for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.delete(
    "/{database_name}/views/delete",
    response_model=ApiResponse[DeleteResponse],
    summary="Wipe views collection for a database",
)
def delete_views(database_name: str) -> ApiResponse[DeleteResponse]:
    """Delete the views collection for a database (all data wiped)."""
    try:
        VectorStore().clear_views(database_name)
        data = DeleteResponse(
            database_name=database_name,
            deleted=["views"],
            message=f"Views collection wiped for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Views deleted successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to delete views for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.delete(
    "/{database_name}/delete",
    response_model=ApiResponse[DeleteResponse],
    summary="Wipe all collections for a database",
)
def delete_database(database_name: str) -> ApiResponse[DeleteResponse]:
    """Drop both schema and views collections for a database entirely."""
    try:
        result = VectorStore().delete_database(database_name)
        data = DeleteResponse(
            database_name=database_name,
            deleted=["schemas", "views"],
            message=(
                f"Deleted {result['schemas_deleted']} schema docs and "
                f"{result['views_deleted']} view docs for '{database_name}'"
            ),
        )
        return ApiResponse(
            success=True, message="Database deleted successfully", data=data
        )
    except Exception as exc:
        logger.error("Failed to delete '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


__all__ = ["router"]
