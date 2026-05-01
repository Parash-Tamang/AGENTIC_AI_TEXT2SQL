import json
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import MetaData, Table, inspect, text

from ..connection import DatabaseConnection
from ..exceptions import SchemaFetchError

logger = logging.getLogger(__name__)

SKIP_SCHEMAS = {
    "mssql": ["sys", "guest", "INFORMATION_SCHEMA"],
    "postgresql": ["pg_catalog", "information_schema", "pg_toast"],
    "mysql": ["information_schema", "performance_schema", "sys", "mysql"],
    "sqlite": [],
}


class ViewColumnSchema(BaseModel):
    name: str
    type: str
    description: Optional[str] = None


class ViewSchema(BaseModel):
    database_name: str
    schema_name: str
    view_name: str
    view_description: Optional[str] = None
    view_definition: Optional[str] = None
    columns: list[ViewColumnSchema]


class ViewService:
    @staticmethod
    def get_views(engine: dict) -> list[ViewSchema]:
        # engine = DatabaseConnection.get_engine()
        if engine is None:
            raise SchemaFetchError("Engine not initialized", code="VW_010")

        inspector = inspect(engine)
        db_type = engine.dialect.name
        skip = SKIP_SCHEMAS.get(db_type, [])
        views: list[ViewSchema] = []

        with engine.connect() as connection:
            db_name = ViewService._resolve_database_name(connection, inspector)

            for schema in inspector.get_schema_names():
                if schema in skip:
                    continue

                for view_name in ViewService._get_view_names(inspector, schema):
                    views.append(
                        ViewService._extract_view(
                            connection=connection,
                            inspector=inspector,
                            db_name=db_name,
                            schema=schema,
                            view_name=view_name,
                        )
                    )

        logger.info("✅ Extracted %s views", len(views))
        return views

    @staticmethod
    def save_views_snapshot(
        views: list[ViewSchema], output_dir: str = "assets/views"
    ) -> Path:
        if not views:
            raise SchemaFetchError("No views to save", code="VW_011")

        database_name = ViewService._sanitize_name(views[0].database_name)
        file_path = Path(output_dir) / f"{database_name}_views.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with file_path.open("w", encoding="utf-8") as file_handle:
            json.dump([view.model_dump() for view in views], file_handle, indent=2)

        logger.info("✅ Views snapshot saved to %s", file_path)
        return file_path

    @staticmethod
    def load_views_snapshot(snapshot_path: str) -> list[ViewSchema]:
        path = Path(snapshot_path)
        if not path.exists():
            raise SchemaFetchError(
                f"Views snapshot not found: {snapshot_path}", code="VW_012"
            )

        with path.open("r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)

        if not isinstance(payload, list):
            raise SchemaFetchError("Invalid views snapshot format", code="VW_013")

        return [ViewSchema.model_validate(item) for item in payload]

    @staticmethod
    def _get_view_names(inspector, schema: str) -> list[str]:
        try:
            return list(inspector.get_view_names(schema=schema))
        except Exception:
            return []

    @staticmethod
    def _resolve_database_name(connection, inspector) -> str:
        dialect = connection.dialect.name
        try:
            if dialect == "mssql":
                value = connection.exec_driver_sql("SELECT DB_NAME()").scalar()
            elif dialect == "postgresql":
                value = connection.exec_driver_sql("SELECT current_database()").scalar()
            elif dialect == "mysql":
                value = connection.exec_driver_sql("SELECT DATABASE()").scalar()
            else:
                value = None
            if value:
                return str(value)
        except Exception:
            pass

        return inspector.default_schema_name or dialect

    @staticmethod
    def _extract_view(
        connection, inspector, db_name: str, schema: str, view_name: str
    ) -> ViewSchema:
        reflected_view = ViewService._reflect_view(connection, schema, view_name)
        view_description = ViewService._get_view_description(
            connection, reflected_view, schema, view_name
        )

        view_definition = ViewService._get_view_definition(inspector, schema, view_name)

        column_descriptions: dict[str, Optional[str]] = {}
        column_types: dict[str, str] = {}
        if reflected_view is not None:
            for column in reflected_view.columns:
                column_descriptions[column.name] = ViewService._get_column_description(
                    connection, reflected_view, schema, view_name, column.name, column
                )
                column_types[column.name] = str(column.type).split("(")[0]

        columns = []
        for column in inspector.get_columns(view_name, schema=schema):
            column_name = column["name"]
            columns.append(
                ViewColumnSchema(
                    name=column_name,
                    type=column_types.get(
                        column_name, str(column["type"]).split("(")[0]
                    ),
                    description=column_descriptions.get(column_name),
                )
            )

        return ViewSchema(
            database_name=db_name,
            schema_name=schema,
            view_name=view_name,
            view_description=view_description,
            view_definition=view_definition,
            columns=columns,
        )

    @staticmethod
    def _reflect_view(connection, schema: str, view_name: str) -> Optional[Table]:
        try:
            metadata = MetaData()
            return Table(view_name, metadata, schema=schema, autoload_with=connection)
        except Exception:
            return None

    @staticmethod
    def _get_view_description(
        connection, reflected_view, schema: str, view_name: str
    ) -> Optional[str]:
        if reflected_view is not None and reflected_view.comment:
            return str(reflected_view.comment)

        if connection.dialect.name == "mssql":
            try:
                query = text("""
                    SELECT CAST(ep.value AS NVARCHAR(MAX))
                    FROM sys.extended_properties ep
                    JOIN sys.views v ON ep.major_id = v.object_id
                    JOIN sys.schemas s ON v.schema_id = s.schema_id
                    WHERE ep.minor_id = 0
                      AND ep.name = 'MS_Description'
                      AND s.name = :schema_name
                      AND v.name = :view_name
                    """)
                value = connection.execute(
                    query, {"schema_name": schema, "view_name": view_name}
                ).scalar()
                return str(value) if value else None
            except Exception:
                return None

        return None

    @staticmethod
    def _get_column_description(
        connection,
        reflected_view,
        schema: str,
        view_name: str,
        column_name: str,
        column,
    ) -> Optional[str]:
        if column.comment:
            return str(column.comment)

        if connection.dialect.name == "mssql":
            try:
                query = text("""
                    SELECT CAST(ep.value AS NVARCHAR(MAX))
                    FROM sys.extended_properties ep
                    JOIN sys.views v ON ep.major_id = v.object_id
                    JOIN sys.schemas s ON v.schema_id = s.schema_id
                    JOIN sys.columns c
                      ON c.object_id = v.object_id
                     AND c.column_id = ep.minor_id
                    WHERE ep.name = 'MS_Description'
                      AND s.name = :schema_name
                      AND v.name = :view_name
                      AND c.name = :column_name
                    """)
                value = connection.execute(
                    query,
                    {
                        "schema_name": schema,
                        "view_name": view_name,
                        "column_name": column_name,
                    },
                ).scalar()
                return str(value) if value else None
            except Exception:
                return None

        return None

    @staticmethod
    def _get_view_definition(inspector, schema: str, view_name: str) -> Optional[str]:
        try:
            definition = inspector.get_view_definition(view_name, schema=schema)
            return str(definition) if definition else None
        except Exception:
            return None

    @staticmethod
    def _sanitize_name(value: str) -> str:
        cleaned = "".join(
            char if char.isalnum() or char in ("-", "_") else "_" for char in value
        )
        return cleaned.strip("_") or "database"


__all__ = ["ViewService", "ViewSchema", "ViewColumnSchema"]
