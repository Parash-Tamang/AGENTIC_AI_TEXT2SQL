"""
Role-Based Access Control (RBAC) Permission Models

Defines Pydantic models for loading and enforcing role-based permissions
on database tables and columns.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional
from pydantic import BaseModel, field_validator, model_validator

FilterType = Literal["id", "enum", "none"]


class ColumnPermission(BaseModel):
    """Schema for a single column permission constraint."""

    filter: FilterType
    values: Optional[list[str | int]] = None

    @field_validator("values", mode="before")
    @classmethod
    def coerce_scalar_to_list(cls, v: object) -> object:
        """Wrap a bare scalar (e.g. "2" or 2) into a single-element list."""
        if v is not None and not isinstance(v, list):
            return [v]
        return v


class TablePermission(BaseModel):
    """Schema for table-level permission with optional column constraints."""

    reason: str
    access_level: Literal["unrestricted", "filtered"]
    required_filters: list[dict] = []  # top-level format (v1)
    columns: dict[str, ColumnPermission] = {}  # column-level format (v2)

    @model_validator(mode="after")
    def normalise_columns(self) -> TablePermission:
        """
        If columns dict is empty but required_filters exist,
        promote required_filters into columns so the rest of the
        codebase only needs to read `self.columns`.
        """
        if not self.columns and self.required_filters:
            for f in self.required_filters:
                col = f["column"]
                ft = f.get("filter_type", "none")
                vals = f.get("values", None)
                self.columns[col] = ColumnPermission(filter=ft, values=vals)
        return self


class PermissionContext(BaseModel):
    """
    Role-scoped RBAC permission context.

    Encapsulates all permissions for a single role and provides
    helper methods for permission checks and policy enforcement.
    """

    role: str
    tables: dict[str, TablePermission]  # key = "SalesLT.TableName"

    # ── helpers ──────────────────────────────────────────────────────────────

    def allowed_tables(self) -> list[str]:
        """Return list of all table names the role can access."""
        return list(self.tables.keys())

    def is_table_allowed(self, table: str) -> bool:
        """Check if a specific table is accessible by this role."""
        return table in self.tables

    def mandatory_filters(self, table: str) -> dict[str, ColumnPermission]:
        """
        Return only columns that carry a real filter (id | enum).

        These are WHERE clause requirements that MUST appear in any query.
        """
        if table not in self.tables:
            return {}
        return {
            col: cp
            for col, cp in self.tables[table].columns.items()
            if cp.filter in ("id", "enum")
        }

    def allowed_columns(self, table: str) -> list[str] | None:
        """
        Return the list of allowed columns for a table.

        None  → unrestricted (all columns allowed).
        list  → explicit whitelist.
        []    → no columns allowed (table exists but no column access).
        """
        tp = self.tables.get(table)
        if tp is None:
            return []
        if tp.access_level == "unrestricted" and not tp.columns:
            return None
        return list(tp.columns.keys())


# ── factory ──────────────────────────────────────────────────────────────────


def build_permission_context(role: str, rbac_json: dict) -> PermissionContext:
    """
    Parse the full RBAC JSON and return a PermissionContext for `role`.

    Args:
        role: One of "customer", "sales", "admin", "analyst", "support".
        rbac_json: Full RBAC dict with shape:
                   {"permissions": {role: {table: {...}}}}

    Returns:
        PermissionContext instance.

    Raises:
        KeyError: If the role is not found in rbac_json["permissions"].
    """
    raw_tables: dict = rbac_json["permissions"][role]
    tables = {
        table_name: TablePermission(**table_data)
        for table_name, table_data in raw_tables.items()
    }
    return PermissionContext(role=role, tables=tables)


@lru_cache(maxsize=1)
def _load_rbac_json() -> dict:
    """Load permissions.json from repo root (cached)."""
    permissions_path = Path(__file__).resolve().parents[2] / "permissions.json"
    with permissions_path.open("r", encoding="utf-8") as file_handle:
        return json.load(file_handle)


def get_permission_context(role: str) -> PermissionContext:
    """Get PermissionContext for a role by reading permissions.json."""
    return build_permission_context(role, _load_rbac_json())


# print(get_permission_context("customer").allowed_tables())
# print(get_permission_context("customer").is_table_allowed("SalesLT.Customer"))
# print(get_permission_context("customer").mandatory_filters("SalesLT.Customer"))
# print(get_permission_context("customer").allowed_columns("SalesLT.Customer"))
