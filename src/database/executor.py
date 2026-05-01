"""Convenience entry points for schema, views, query, and view execution."""

from __future__ import annotations

from typing import Optional

from .service.execution_service import DatabaseExecutionService
from .service.schema_service import ExclusionConfig

DatabaseExecutor = DatabaseExecutionService


def build_executor(
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
) -> DatabaseExecutionService:
    return DatabaseExecutionService.from_parts(
        db_type=db_type,
        server=server,
        database=database,
        username=username,
        password=password,
        pool_size=pool_size,
        timeout=timeout,
        port=port,
    )


def generate_schema(
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
    exclusions: Optional[ExclusionConfig] = None,
):
    return build_executor(
        db_type=db_type,
        server=server,
        database=database,
        username=username,
        password=password,
        pool_size=pool_size,
        timeout=timeout,
        port=port,
    ).generate_schema(exclusions=exclusions)


def generate_views(
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
):
    return build_executor(
        db_type=db_type,
        server=server,
        database=database,
        username=username,
        password=password,
        pool_size=pool_size,
        timeout=timeout,
        port=port,
    ).generate_views()


def execute_query(
    sql: str,
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
    max_rows: int = 100,
    expected_columns=None,
):
    return build_executor(
        db_type=db_type,
        server=server,
        database=database,
        username=username,
        password=password,
        pool_size=pool_size,
        timeout=timeout,
        port=port,
    ).execute_query(
        sql,
        max_rows=max_rows,
        expected_columns=expected_columns,
    )


def execute_view(
    view_name: str,
    *,
    db_type: str,
    server: Optional[str],
    database: str,
    username: str,
    password: str,
    pool_size: int = 5,
    timeout: int = 30,
    port: Optional[int] = None,
    schema: Optional[str] = None,
    max_rows: int = 100,
    expected_columns=None,
):
    return build_executor(
        db_type=db_type,
        server=server,
        database=database,
        username=username,
        password=password,
        pool_size=pool_size,
        timeout=timeout,
        port=port,
    ).execute_view(
        view_name,
        schema=schema,
        max_rows=max_rows,
        expected_columns=expected_columns,
    )


__all__ = [
    "DatabaseExecutor",
    "DatabaseExecutionService",
    "build_executor",
    "generate_schema",
    "generate_views",
    "execute_query",
    "execute_view",
]
