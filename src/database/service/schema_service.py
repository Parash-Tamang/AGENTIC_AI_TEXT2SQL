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

SAMPLE_SIZE = 3


class ExclusionConfig(BaseModel):
    schemas: list[str] = []
    tables: list[str] = []  # Format: "schema.table"
    columns: list[str] = []  # Format: "schema.table.column"


class ColumnSchema(BaseModel):
    name: str
    type: str
    constraint: str
    relation: Optional[str] = None
    description: Optional[str] = None
    sample_values: list[str] = []


class TableSchema(BaseModel):
    database_name: str
    schema_name: str
    table_name: str
    table_description: Optional[str] = None
    columns: list[ColumnSchema]


class SchemaService:
    @staticmethod
    def get_schema(
        engine: dict, exclusions: Optional[ExclusionConfig] = None
    ) -> list[TableSchema]:
        # engine = DatabaseConnection.get_engine()
        if engine is None:
            raise SchemaFetchError("Engine not initialized", code="SCH_010")

        excl = exclusions or ExclusionConfig()
        # Pre-build sets for O(1) lookup
        excluded_schemas = set(excl.schemas)
        excluded_tables = set(excl.tables)  # e.g. {"public.users"}
        excluded_columns = set(excl.columns)  # e.g. {"public.orders.customer_pii"}

        inspector = inspect(engine)
        db_type = engine.dialect.name
        skip = SKIP_SCHEMAS.get(db_type, [])
        tables: list[TableSchema] = []

        with engine.connect() as connection:
            db_name = SchemaService._resolve_database_name(connection, inspector)

            for schema in inspector.get_schema_names():
                if schema in skip or schema in excluded_schemas:
                    logger.debug("⏭️  Skipping excluded schema: %s", schema)
                    continue

                for table_name in inspector.get_table_names(schema=schema):
                    table_key = f"{schema}.{table_name}"
                    if table_key in excluded_tables:
                        logger.debug("⏭️  Skipping excluded table: %s", table_key)
                        continue

                    tables.append(
                        SchemaService._extract_table(
                            connection=connection,
                            inspector=inspector,
                            db_name=db_name,
                            schema=schema,
                            table=table_name,
                            excluded_columns=excluded_columns,
                        )
                    )

        logger.info("✅ Extracted %s tables", len(tables))
        return tables

    @staticmethod
    def save_schema_snapshot(
        tables: list[TableSchema], output_dir: str = "assets/schema"
    ) -> Path:
        if not tables:
            raise SchemaFetchError("No schema tables to save", code="SCH_011")

        database_name = SchemaService._sanitize_name(tables[0].database_name)
        file_path = Path(output_dir) / f"{database_name}_schema.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with file_path.open("w", encoding="utf-8") as file_handle:
            json.dump([table.model_dump() for table in tables], file_handle, indent=2)

        logger.info("✅ Schema snapshot saved to %s", file_path)
        return file_path

    @staticmethod
    def load_schema_snapshot(snapshot_path: str) -> list[TableSchema]:
        path = Path(snapshot_path)
        if not path.exists():
            raise SchemaFetchError(
                f"Schema snapshot not found: {snapshot_path}", code="SCH_012"
            )

        with path.open("r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)

        if not isinstance(payload, list):
            raise SchemaFetchError(
                "Invalid schema snapshot payload format", code="SCH_013"
            )

        return [TableSchema.model_validate(item) for item in payload]

    @staticmethod
    def to_llm_string(tables: list[TableSchema]) -> str:
        lines = []
        for table in tables:
            cols = []
            for column in table.columns:
                col_str = f"{column.name} ({column.type})"
                if column.constraint == "Primary Key":
                    col_str += " PK"
                elif column.constraint == "Foreign Key":
                    col_str += f" FK→{column.relation}"
                cols.append(col_str)
            lines.append(f"{table.schema_name}.{table.table_name}({', '.join(cols)})")
        return "\n".join(lines)

    @staticmethod
    def _resolve_database_name(connection, inspector) -> str:
        dialect = connection.dialect.name
        try:
            if dialect == "mssql":
                value = connection.execute(text("SELECT DB_NAME()")).scalar()
            elif dialect == "postgresql":
                value = connection.execute(text("SELECT current_database()")).scalar()
            elif dialect == "mysql":
                value = connection.execute(text("SELECT DATABASE()")).scalar()
            else:
                value = None
            if value:
                return str(value)
        except Exception:
            pass

        return inspector.default_schema_name or dialect

    @staticmethod
    def _extract_table(
        connection,
        inspector,
        db_name: str,
        schema: str,
        table: str,
        excluded_columns: set[str] | None = None,
    ) -> TableSchema:
        excluded_columns = excluded_columns or set()

        reflected_table = SchemaService._reflect_table(connection, schema, table)
        table_description = (
            str(reflected_table.comment)
            if reflected_table is not None and reflected_table.comment
            else None
        )

        column_descriptions: dict[str, Optional[str]] = {}
        if reflected_table is not None:
            for column in reflected_table.columns:
                column_descriptions[column.name] = (
                    str(column.comment) if column.comment else None
                )

        pk_columns = inspector.get_pk_constraint(table, schema=schema)[
            "constrained_columns"
        ]

        fk_info = inspector.get_foreign_keys(table, schema=schema)
        fk_lookup = {}
        for fk in fk_info:
            for col, ref_col in zip(fk["constrained_columns"], fk["referred_columns"]):
                fk_lookup[col] = f"{fk['referred_table']}.{ref_col}"

        all_col_names = [c["name"] for c in inspector.get_columns(table, schema=schema)]

        # Filter out excluded columns before fetching samples — avoids
        # selecting sensitive data we never intend to surface.
        included_col_names = [
            col
            for col in all_col_names
            if f"{schema}.{table}.{col}" not in excluded_columns
        ]

        sample_map = SchemaService._get_sample_values(
            connection, schema, table, included_col_names
        )

        columns = []
        for col in inspector.get_columns(table, schema=schema):
            col_name = col["name"]
            col_key = f"{schema}.{table}.{col_name}"

            if col_key in excluded_columns:
                logger.debug("⏭️  Skipping excluded column: %s", col_key)
                continue

            if col_name in pk_columns:
                constraint = "Primary Key"
            elif col_name in fk_lookup:
                constraint = "Foreign Key"
            elif col.get("nullable", True):
                constraint = "nullable"
            else:
                constraint = "not null"

            columns.append(
                ColumnSchema(
                    name=col_name,
                    type=str(col["type"]).split("(")[0],
                    constraint=constraint,
                    relation=fk_lookup.get(col_name),
                    description=column_descriptions.get(col_name),
                    sample_values=sample_map.get(col_name, []),
                )
            )

        return TableSchema(
            database_name=db_name,
            schema_name=schema,
            table_name=table,
            table_description=table_description,
            columns=columns,
        )

    @staticmethod
    def _reflect_table(connection, schema: str, table: str) -> Optional[Table]:
        try:
            metadata = MetaData()
            return Table(table, metadata, schema=schema, autoload_with=connection)
        except Exception:
            return None

    @staticmethod
    def _get_sample_values(
        connection, schema: str, table: str, col_names: list[str]
    ) -> dict[str, list[str]]:
        sample_map = {col: [] for col in col_names}
        dialect = connection.dialect.name
        table_ref = (
            f"[{schema}].[{table}]" if dialect == "mssql" else f'"{schema}"."{table}"'
        )
        limit_sql = f"SELECT * FROM {table_ref} LIMIT {SAMPLE_SIZE}"
        if dialect == "mssql":
            limit_sql = f"SELECT TOP {SAMPLE_SIZE} * FROM {table_ref}"

        try:
            rows = connection.execute(text(limit_sql)).fetchall()
            for col in col_names:
                values = []
                for row in rows:
                    row_dict = dict(row._mapping)
                    val = row_dict.get(col)
                    if val is not None:
                        values.append(str(val))
                sample_map[col] = values
        except Exception as exc:
            logger.warning(
                "⚠️ Could not fetch samples for %s.%s: %s", schema, table, exc
            )

        return sample_map

    @staticmethod
    def _sanitize_name(value: str) -> str:
        cleaned = "".join(
            char if char.isalnum() or char in ("-", "_") else "_" for char in value
        )
        return cleaned.strip("_") or "database"


__all__ = ["SchemaService", "TableSchema", "ColumnSchema", "ExclusionConfig"]
