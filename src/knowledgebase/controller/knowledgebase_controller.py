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
from src.knowledgebase.config.graph_setting import (
    GraphSettings,
    DEFAULT_GRAPH_SETTINGS,
    graph_manager,
)
from src.knowledgebase.config.schema_setting import (
    SchemaSettings,
    DEFAULT_Schema_SETTINGS,
)

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


class GraphResponse(BaseModel):
    database_name: str
    graph_path: str
    message: str


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
        else:
            logger.warning("Schema graph does not exist for '%s'", database_name)
        # Unload from memory
        if graph_manager.is_loaded(database_name):
            graph_manager.unload(database_name)
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
    deleted_items = []
    message_parts = []

    try:
        VectorStore().clear_schemas(database_name)
        deleted_items.append("schemas")
        message_parts.append("schemas removed")
        logger.info("Schemas deleted for '%s'", database_name)
    except Exception as exc:
        error_msg = str(exc)
        if "does not exist" in error_msg:
            logger.warning("Schema collection does not exist for '%s'", database_name)
        else:
            logger.error("Failed to delete schemas for '%s': %s", database_name, exc)

    # Delete schema graph too
    graph_dir = os.path.join(
        DEFAULT_GRAPH_SETTINGS.persist_directory, database_name.lower()
    )
    if os.path.exists(graph_dir):
        try:
            _delete_schema_graphs(database_name)
            deleted_items.append("schema_graph")
            message_parts.append("graph removed")
        except Exception as exc:
            logger.warning(
                "Could not delete schema graph for '%s': %s", database_name, exc
            )

    if message_parts:
        message = ", ".join(message_parts) + f" for '{database_name}'"
    else:
        message = f"No schemas found for '{database_name}'"

    data = DeleteResponse(
        database_name=database_name,
        deleted=deleted_items,
        message=message,
    )
    return ApiResponse(success=True, message="Schemas deleted successfully", data=data)


@router.delete(
    "/{database_name}/views/delete",
    response_model=ApiResponse[DeleteResponse],
    summary="Wipe views collection for a database",
)
def delete_views(database_name: str) -> ApiResponse[DeleteResponse]:
    """Delete the views collection and graph for a database (all data wiped)."""
    deleted_items = []
    message_parts = []

    try:
        VectorStore().clear_views(database_name)
        deleted_items.append("views")
        message_parts.append("views removed")
        logger.info("Views deleted for '%s'", database_name)
    except Exception as exc:
        error_msg = str(exc)
        if "does not exist" in error_msg:
            logger.warning("Views collection does not exist for '%s'", database_name)
        else:
            logger.error("Failed to delete views for '%s': %s", database_name, exc)

    # Delete schema graph too
    graph_dir = os.path.join(
        DEFAULT_GRAPH_SETTINGS.persist_directory, database_name.lower()
    )
    if os.path.exists(graph_dir):
        try:
            _delete_schema_graphs(database_name)
            deleted_items.append("schema_graph")
            message_parts.append("graph removed")
        except Exception as exc:
            logger.warning(
                "Could not delete schema graph for '%s': %s", database_name, exc
            )

    if message_parts:
        message = ", ".join(message_parts) + f" for '{database_name}'"
    else:
        message = f"No views found for '{database_name}'"

    data = DeleteResponse(
        database_name=database_name,
        deleted=deleted_items,
        message=message,
    )
    return ApiResponse(success=True, message="Views deleted successfully", data=data)


@router.delete(
    "/{database_name}/delete",
    response_model=ApiResponse[DeleteResponse],
    summary="Wipe all collections for a database",
)
def delete_database(database_name: str) -> ApiResponse[DeleteResponse]:
    """Drop both schema and views collections, and schema graph for a database entirely."""
    deleted_items = []
    message_parts = []

    # Try to delete schemas
    try:
        result = VectorStore().delete_database(database_name)
        if result["schemas_deleted"] > 0:
            deleted_items.append("schemas")
            message_parts.append(f"schemas removed")
            logger.info(
                "Deleted %d schema docs for '%s'",
                result["schemas_deleted"],
                database_name,
            )
    except Exception as exc:
        error_msg = str(exc)
        if "does not exist" in error_msg:
            logger.warning("Schemas collection does not exist for '%s'", database_name)
        else:
            logger.error("Failed to delete schemas for '%s': %s", database_name, exc)

    # Try to delete views
    try:
        if (
            database_name in VectorStore().list_databases()
            and "views" in VectorStore().list_databases()[database_name]
        ):
            VectorStore().clear_views(database_name)
            deleted_items.append("views")
            message_parts.append("views removed")
            logger.info("Views deleted for '%s'", database_name)
    except Exception as exc:
        error_msg = str(exc)
        if "does not exist" in error_msg:
            logger.warning("Views collection does not exist for '%s'", database_name)
        else:
            logger.error("Failed to delete views for '%s': %s", database_name, exc)

    # Try to delete schema graph
    graph_dir = os.path.join(
        DEFAULT_GRAPH_SETTINGS.persist_directory, database_name.lower()
    )
    if os.path.exists(graph_dir):
        try:
            _delete_schema_graphs(database_name)
            deleted_items.append("schema_graph")
            message_parts.append("graph removed")
            logger.info("Schema graph deleted for '%s'", database_name)
        except Exception as exc:
            logger.warning(
                "Could not delete schema graph for '%s': %s", database_name, exc
            )
    else:
        logger.debug("No schema graph found for '%s'", database_name)

    if message_parts:
        message = ", ".join(message_parts) + f" for '{database_name}'"
    else:
        message = f"No data to delete for '{database_name}'"

    data = DeleteResponse(
        database_name=database_name,
        deleted=deleted_items,
        message=message,
    )
    return ApiResponse(success=True, message="Database deleted successfully", data=data)


# ── GRAPHS ────────────────────────────────────────────────────────────────────


@router.post(
    "/{database_name}/graphs/create",
    response_model=ApiResponse[GraphResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Build and save schema graph from indexed schema",
)
def create_graph(database_name: str) -> ApiResponse[GraphResponse]:
    """Build schema graph from the indexed schema snapshot."""
    try:
        # Get schema snapshot path
        schema_file = os.path.join(
            DEFAULT_Schema_SETTINGS.persist_directory,
            f"{database_name}_schema.json",
        )
        print(schema_file)
        if not os.path.exists(schema_file):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No schema snapshot found for '{database_name}'. Create schemas first.",
            )

        graph_path = _build_schema_graphs(database_name, schema_file)
        data = GraphResponse(
            database_name=database_name,
            graph_path=graph_path,
            message=f"Schema graph created for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Graph created successfully", data=data
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to create graph for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.put(
    "/{database_name}/graphs/update",
    response_model=ApiResponse[GraphResponse],
    summary="Rebuild schema graph from indexed schema",
)
def update_graph(database_name: str) -> ApiResponse[GraphResponse]:
    """Wipe and rebuild schema graph from the latest indexed schema snapshot."""
    try:
        # Get schema snapshot path
        schema_file = os.path.join(
            SchemaService.get_persist_directory(),
            f"{database_name}_schema_snapshot.json",
        )
        if not os.path.exists(schema_file):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No schema snapshot found for '{database_name}'. Create schemas first.",
            )

        # Delete existing graph
        _delete_schema_graphs(database_name)
        # Rebuild graph
        graph_path = _build_schema_graphs(database_name, schema_file)
        data = GraphResponse(
            database_name=database_name,
            graph_path=graph_path,
            message=f"Schema graph rebuilt for '{database_name}'",
        )
        return ApiResponse(
            success=True, message="Graph updated successfully", data=data
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update graph for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


@router.delete(
    "/{database_name}/graphs/delete",
    response_model=ApiResponse[DeleteResponse],
    summary="Delete schema graph for a database",
)
def delete_graph(database_name: str) -> ApiResponse[DeleteResponse]:
    """Delete the schema graph for a database."""
    try:
        graph_dir = os.path.join(
            DEFAULT_GRAPH_SETTINGS.persist_directory, database_name.lower()
        )
        if os.path.exists(graph_dir):
            _delete_schema_graphs(database_name)
            data = DeleteResponse(
                database_name=database_name,
                deleted=["schema_graph"],
                message=f"Schema graph deleted for '{database_name}'",
            )
            return ApiResponse(
                success=True, message="Graph deleted successfully", data=data
            )
        else:
            logger.warning("Schema graph does not exist for '%s'", database_name)
            data = DeleteResponse(
                database_name=database_name,
                deleted=[],
                message=f"No schema graph found for '{database_name}'",
            )
            return ApiResponse(success=True, message="No graph to delete", data=data)
    except Exception as exc:
        logger.error("Failed to delete graph for '%s': %s", database_name, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )


__all__ = ["router"]
