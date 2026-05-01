"""Safe execution service for validated queries and views."""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import pandas as pd
from sqlalchemy import inspect, text
from pydantic import ValidationError

from ..config.connection_builder import ConnectionBuilder
from ..connection import DatabaseConnection
from ..error_parser import DatabaseErrorParser
from ..exceptions import DatabaseConnectionError, DatabaseQueryError
from .schema_service import SchemaService
from .view_service import ViewService
from ..validations.query_validator import QueryValidator
from ..validations.results_validator import ResultValidator

logger = logging.getLogger(__name__)

SKIP_SCHEMAS = {
    "mssql": ["sys", "guest", "INFORMATION_SCHEMA"],
    "postgresql": ["pg_catalog", "information_schema", "pg_toast"],
    "mysql": ["information_schema", "performance_schema", "sys", "mysql"],
    "sqlite": [],
}


class DatabaseExecutionService:
    """Execute read-only SQL queries or existing views with validation."""

    def __init__(
        self,
        *,
        connection_string: Optional[str] = None,
        pool_size: int = 5,
        pool_timeout: int = 30,
        builder: Optional[ConnectionBuilder] = None,
    ):
        if builder is None and not connection_string:
            raise DatabaseConnectionError(
                "Either connection_string or builder must be provided",
                code="DB_010",
            )

        self._builder = builder
        self._connection_string = connection_string
        self._pool_size = pool_size
        self._pool_timeout = pool_timeout

    @classmethod
    def from_builder(cls, builder: ConnectionBuilder) -> "DatabaseExecutionService":
        return cls(builder=builder)

    @classmethod
    def from_parts(
        cls,
        *,
        db_type: str,
        server: Optional[str],
        database: str,
        username: str,
        password: str,
        pool_size: int = 5,
        timeout: int = 30,
        port: Optional[int] = None,
    ) -> "DatabaseExecutionService":
        builder = ConnectionBuilder(
            DB_TYPE=db_type,
            SERVER=server,
            DATABASE=database,
            USERNAME=username,
            PASSWORD=password,
            POOL_SIZE=pool_size,
            TIMEOUT=timeout,
            PORT=port,
        )
        return cls(builder=builder)

    def _resolve_connection_string(self) -> str:
        if self._builder is not None:
            return self._builder.build()
        if self._connection_string:
            return self._connection_string
        raise DatabaseConnectionError(
            "Connection information is missing", code="DB_010"
        )

    def _get_engine(self):
        connection_string = self._resolve_connection_string()
        return DatabaseConnection.create_engine(
            connection_string=connection_string,
            pool_size=self._pool_size,
            pool_timeout=self._pool_timeout,
        )

    def _get_dialect(self) -> str:
        """Get the database dialect from the engine."""
        try:
            engine = self._get_engine()
            return engine.dialect.name
        except Exception:
            return "mssql"  # Default dialect

    def execute_query(
        self,
        sql: str,
        *,
        max_rows: int = 100,
        expected_columns: Optional[Iterable[str]] = None,
    ) -> pd.DataFrame:
        """Validate and execute a safe read-only SQL query."""
        try:
            try:
                query = QueryValidator(sql=sql, max_rows=max_rows)
            except ValidationError as e:
                # Extract first error for clean message
                first_error = e.errors()[0]
                field = first_error["loc"][0]
                msg = first_error["msg"]
                logger.error(f"Query validation failed: {field} - {msg}")
                raise DatabaseQueryError(
                    f"Invalid {field}: {msg}",
                    code="SQL_001",
                ) from e

            return self._run_dataframe_query(
                query.sql,
                max_rows=query.max_rows,
                expected_columns=expected_columns,
            )
        except DatabaseConnectionError:
            raise
        except DatabaseQueryError:
            raise
        except Exception as exc:
            dialect = self._get_dialect()
            parsed_error = DatabaseErrorParser.parse(exc, dialect=dialect)
            error_message = parsed_error.get("message", str(exc))
            raise DatabaseQueryError(
                f"Query execution failed: {error_message}",
                code="SQL_001",
            )

    def execute_view(
        self,
        view_name: str,
        *,
        schema: Optional[str] = None,
        max_rows: int = 100,
        expected_columns: Optional[Iterable[str]] = None,
    ) -> pd.DataFrame:
        """Validate view existence and execute a SELECT against it."""
        try:
            engine = self._get_engine()
            inspector = inspect(engine)
            db_type = engine.dialect.name

            resolved_schema = schema or self._find_view_schema(
                inspector=inspector,
                db_type=db_type,
                view_name=view_name,
            )
            if resolved_schema is None:
                raise DatabaseQueryError(
                    f"View not found: {view_name}",
                    code="VW_001",
                )

            self._validate_view_exists(inspector, resolved_schema, view_name)
            query = self._build_view_query(db_type, resolved_schema, view_name)
            return self._run_dataframe_query(
                query,
                max_rows=max_rows,
                expected_columns=expected_columns,
            )
        except DatabaseConnectionError:
            raise
        except DatabaseQueryError:
            raise
        except Exception as exc:
            dialect = self._get_dialect()
            parsed_error = DatabaseErrorParser.parse(exc, dialect=dialect)
            error_message = parsed_error.get("message", str(exc))
            raise DatabaseQueryError(
                f"View execution failed: {error_message}",
                code="VW_003",
            )

    def generate_schema(
        self, exclusions: Optional[SchemaService.ExclusionConfig] = None
    ):
        """Generate schema metadata after initializing the connection."""
        engine = self._get_engine()
        return SchemaService.get_schema(engine=engine, exclusions=exclusions)

    def generate_views(self):
        """Generate view metadata after initializing the connection."""
        engine = self._get_engine()
        return ViewService.get_views(engine=engine)

    def fetch_one(self, sql: str) -> dict:
        """Execute a safe query and return the first row as a dictionary."""
        df = self.execute_query(sql, max_rows=1)
        return df.iloc[0].to_dict()

    def close(self):
        """Dispose the shared engine."""
        DatabaseConnection.dispose()

    def _run_dataframe_query(
        self,
        query_text: str,
        *,
        max_rows: int,
        expected_columns: Optional[Iterable[str]],
    ) -> pd.DataFrame:
        engine = self._get_engine()

        with engine.connect() as conn:
            df = pd.read_sql_query(text(query_text), conn)

        ResultValidator.validate_not_empty(df, query_text)
        if expected_columns is not None:
            ResultValidator.validate_expected_columns(df, list(expected_columns))
        ResultValidator.validate_row_limit(df, max_rows)

        logger.info("✅ Execution completed safely")
        return df

    @staticmethod
    def _find_view_schema(inspector, db_type: str, view_name: str) -> Optional[str]:
        skip = SKIP_SCHEMAS.get(db_type, [])
        for schema in inspector.get_schema_names():
            if schema in skip:
                continue
            if view_name in inspector.get_view_names(schema=schema):
                return schema
        return None

    @staticmethod
    def _validate_view_exists(inspector, schema: str, view_name: str) -> None:
        if view_name not in inspector.get_view_names(schema=schema):
            raise DatabaseQueryError(
                f"View not found: {schema}.{view_name}",
                code="VW_002",
            )

    @staticmethod
    def _build_view_query(dialect: str, schema: str, view_name: str) -> str:
        if dialect == "mssql":
            return f"SELECT * FROM [{schema}].[{view_name}]"
        if dialect == "mysql":
            return f"SELECT * FROM `{schema}`.`{view_name}`"
        return f'SELECT * FROM "{schema}"."{view_name}"'


__all__ = ["DatabaseExecutionService"]
