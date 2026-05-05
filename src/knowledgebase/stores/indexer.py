from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field, model_validator

from src.database.service.schema_service import TableSchema
from src.database.service.view_service import ViewSchema
from src.knowledgebase.config.vector_setting import DEFAULT_SETTINGS, VectorSettings
from .embedder import Embedder
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

_SAMPLE_LIMIT = 3


# ── Enums ─────────────────────────────────────────────────────────────────────


class Constraint(str, Enum):
    PK = "PK"
    FK = "FK"
    NOT_NULL = "NOT NULL"
    NULL = "NULL"


class SchemaType(str, Enum):
    TABLE = "table"
    VIEW = "view"


# ── Pydantic models ───────────────────────────────────────────────────────────


class ColumnModel(BaseModel):
    name: str
    type: str = "UNKNOWN"
    constraint: str = ""
    relation: Optional[str] = None
    description: Optional[str] = None
    sample_values: list[str] = Field(default_factory=list)

    @property
    def normalized_constraint(self) -> Constraint:
        upper = self.constraint.upper().strip()
        if "PRIMARY" in upper or upper == "PK":
            return Constraint.PK
        if "FOREIGN" in upper or upper == "FK" or self.relation:
            return Constraint.FK
        if "NOT NULL" in upper:
            return Constraint.NOT_NULL
        return Constraint.NULL

    @property
    def field_description(self) -> str:
        if self.description:
            base = self.description.strip().rstrip(".")
            return f"{base}. Links to {self.relation}" if self.relation else base
        if self.relation:
            return f"Foreign key → {self.relation}"
        if self.sample_values:
            preview = ", ".join(str(v) for v in self.sample_values[:_SAMPLE_LIMIT])
            return f"Example values: {preview}"
        return f"{self.name} field"


class TableModel(BaseModel):
    database_name: str
    schema_name: str
    table_name: str
    table_description: Optional[str] = None
    columns: list[ColumnModel] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_columns(cls, values: dict[str, Any]) -> dict[str, Any]:
        cols = values.get("columns", [])
        values["columns"] = [
            ColumnModel(**c) if isinstance(c, dict) else c for c in cols
        ]
        return values

    @property
    def doc_id(self) -> str:
        return f"{self.database_name}.{self.schema_name}.{self.table_name}"

    def to_document(self) -> str:
        lines = [
            f"Table: {self.table_name}",
            f"Context: {self.table_description or ''}",
            "Fields:",
        ]
        for col in self.columns:
            lines.append(f"  - {col.name}: {col.field_description}.")
        return "\n".join(lines)

    def to_metadata(self) -> dict[str, Any]:
        columns_metadata = [
            [col.name, col.type, col.normalized_constraint.value, col.relation]
            for col in self.columns
        ]
        return {
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "type": SchemaType.TABLE,
            "columns": json.dumps(columns_metadata),
        }


class ViewColumnModel(BaseModel):
    name: str
    type: str = "UNKNOWN"
    description: Optional[str] = None


class ViewModel(BaseModel):
    database_name: str
    schema_name: str
    view_name: str
    view_description: Optional[str] = None
    columns: list[ViewColumnModel] = Field(default_factory=list)
    view_definition: Optional[str] = None

    @property
    def doc_id(self) -> str:
        return f"{self.database_name}.{self.schema_name}.{self.view_name}"

    def to_document(self) -> str:
        lines = [f"View: {self.schema_name}.{self.view_name}"]
        if self.view_description:
            lines.append(f"Description: {self.view_description}")
        lines.append("Columns:")
        for col in self.columns:
            parts = [f"  - {col.name} ({col.type})"]
            if col.description:
                parts.append(f"| Info: {col.description}")
            lines.append(" ".join(parts))
        if self.view_definition:
            lines.append(f"Definition:\n{self.view_definition.strip()}")
        return "\n".join(lines)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "view_name": self.view_name,
            "type": SchemaType.VIEW,
        }


class IndexEntry(BaseModel):
    doc_id: str
    document: str
    metadata: dict[str, Any]
    model_config = {"frozen": True}


# ── Indexer ───────────────────────────────────────────────────────────────────


class Indexer:
    def __init__(
        self,
        settings: VectorSettings = DEFAULT_SETTINGS,
        embedder: Optional[Embedder] = None,
        store: Optional[VectorStore] = None,
    ) -> None:
        self._settings = settings
        self._embedder = embedder or Embedder(settings)
        self._store = store or VectorStore(settings)

    # ── Public API ────────────────────────────────────────────────────────────

    def index_json_from_file(
        self, database_name: str, schema_type: SchemaType, json_path: str | Path
    ) -> int:
        """Load a JSON schema file and index all entries it contains."""
        path = Path(json_path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.error("JSON file not found: %s", json_path)
            return 0
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in %s: %s", json_path, exc)
            return 0

        records = data if isinstance(data, list) else [data]
        return self.index_raw_data(database_name, records, schema_type)

    def index_raw_data(
        self, database_name: str, data_list: list[dict], schema_type: SchemaType
    ) -> int:
        """Index raw dicts as either tables or views based on schema_type."""
        if not data_list:
            logger.warning("No data provided to index_raw_data")
            return 0

        if schema_type == SchemaType.TABLE:
            model_cls = TableModel
            store_fn = lambda ids, docs, embs, metas: self._store.upsert_schemas(
                database_name, ids, docs, embs, metas
            )
        else:
            model_cls = ViewModel
            store_fn = lambda ids, docs, embs, metas: self._store.upsert_views(
                database_name, ids, docs, embs, metas
            )

        entries: list[IndexEntry] = []
        for raw in data_list:
            try:
                model = model_cls(**raw)
                entries.append(
                    IndexEntry(
                        doc_id=model.doc_id,
                        document=model.to_document(),
                        metadata=model.to_metadata(),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed %s dict: %s", schema_type.value, exc)

        return self._upsert(entries, store_fn=store_fn, label=f"{schema_type.value}s")

    def index_schemas(self, database_name: str, tables: list[TableSchema]) -> int:
        """Embed and store typed TableSchema objects."""
        if not tables:
            logger.warning("No tables provided to index_schemas")
            return 0

        entries = [
            IndexEntry(
                doc_id=f"{t.database_name}.{t.schema_name}.{t.table_name}",
                document=self._format_table_schema(t),
                metadata={
                    "database_name": t.database_name,
                    "schema_name": t.schema_name,
                    "table_name": t.table_name,
                    "type": SchemaType.TABLE,
                },
            )
            for t in tables
        ]
        store_fn = lambda ids, docs, embs, metas: self._store.upsert_schemas(
            database_name, ids, docs, embs, metas
        )
        return self._upsert(entries, store_fn, "table schemas")

    def index_views(self, database_name: str, views: list[ViewSchema]) -> int:
        """Embed and store typed ViewSchema objects."""
        if not views:
            logger.warning("No views provided to index_views")
            return 0

        entries = [
            IndexEntry(
                doc_id=f"{v.database_name}.{v.schema_name}.{v.view_name}",
                document=self._format_view_schema(v),
                metadata={
                    "database_name": v.database_name,
                    "schema_name": v.schema_name,
                    "view_name": v.view_name,
                    "type": SchemaType.VIEW,
                },
            )
            for v in views
        ]
        store_fn = lambda ids, docs, embs, metas: self._store.upsert_views(
            database_name, ids, docs, embs, metas
        )
        return self._upsert(entries, store_fn, "views")

    def index_all(
        self, database_name: str, tables: list[TableSchema], views: list[ViewSchema]
    ) -> dict[str, int]:
        """Index both tables and views in a single call."""
        return {
            "tables_indexed": self.index_schemas(database_name, tables),
            "views_indexed": self.index_views(database_name, views),
        }

    def update_from_file(
        self, database_name: str, schema_type: SchemaType, json_path: str | Path
    ) -> int:
        """Wipe collection then reload from JSON file. Removes ghost entries."""
        if schema_type == SchemaType.TABLE:
            self._store.clear_schemas(database_name)
        else:
            self._store.clear_views(database_name)

        return self.index_json_from_file(database_name, schema_type, json_path)

    def update_schemas(self, database_name: str, tables: list[TableSchema]) -> int:
        """Wipe schema collection and reload from typed TableSchema objects."""
        if not tables:
            logger.warning("No tables provided — aborting to avoid wiping collection")
            return 0
        self._store.clear_schemas(database_name)
        return self.index_schemas(database_name, tables)

    def update_views(self, database_name: str, views: list[ViewSchema]) -> int:
        """Wipe views collection and reload from typed ViewSchema objects."""
        if not views:
            logger.warning("No views provided — aborting to avoid wiping collection")
            return 0
        self._store.clear_views(database_name)
        return self.index_views(database_name, views)

    def update_all(
        self, database_name: str, tables: list[TableSchema], views: list[ViewSchema]
    ) -> dict[str, int]:
        """Wipe and reload both collections in one call."""
        return {
            "tables_indexed": self.update_schemas(database_name, tables),
            "views_indexed": self.update_views(database_name, views),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _upsert(self, entries: list[IndexEntry], store_fn: Callable, label: str) -> int:
        if not entries:
            logger.warning("No valid entries to index for %s", label)
            return 0

        ids = [e.doc_id for e in entries]
        documents = [e.document for e in entries]
        metadatas = [e.metadata for e in entries]

        try:
            embeddings = self._embedder.embed_batch(documents)
            store_fn(ids, documents, embeddings, metadatas)
            logger.info("Indexed %d %s", len(ids), label)
            return len(ids)
        except Exception as exc:
            logger.error("Failed to index %s: %s", label, exc)
            return 0

    # ── Text formatters ───────────────────────────────────────────────────────

    @staticmethod
    def _format_table_schema(table: TableSchema) -> str:
        lines = [f"Table: {table.schema_name}.{table.table_name}"]
        if table.table_description:
            lines.append(f"Description: {table.table_description}")
        lines.append("Columns:")
        for col in table.columns:
            upper = (col.constraint or "").upper().strip()
            if "PRIMARY" in upper or upper == "PK":
                constraint = Constraint.PK
            elif "FOREIGN" in upper or upper == "FK" or col.relation:
                constraint = Constraint.FK
            elif "NOT NULL" in upper:
                constraint = Constraint.NOT_NULL
            else:
                constraint = Constraint.NULL
            parts = [f"  - {col.name} ({col.type}) [{constraint.value}]"]
            if col.relation:
                parts.append(f"→ {col.relation}")
            if col.description:
                parts.append(f"| Info: {col.description}")
            if col.sample_values:
                preview = ", ".join(col.sample_values[:_SAMPLE_LIMIT])
                parts.append(f"| Samples: {preview}")
            lines.append(" ".join(parts))
        return "\n".join(lines)

    @staticmethod
    def _format_view_schema(view: ViewSchema) -> str:
        lines = [f"View: {view.schema_name}.{view.view_name}"]
        if view.view_description:
            lines.append(f"Description: {view.view_description}")
        lines.append("Columns:")
        for col in view.columns:
            parts = [f"  - {col.name} ({col.type})"]
            if col.description:
                parts.append(f"| Info: {col.description}")
            lines.append(" ".join(parts))
        if view.view_definition:
            lines.append(f"Definition:\n{view.view_definition.strip()}")
        return "\n".join(lines)


__all__ = ["Indexer"]
