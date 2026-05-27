from __future__ import annotations

import httpx

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SessionContext(BaseModel):
    session_id: Optional[str] = Field(None, description="Session identifier")
    # user_id: Optional[str] = Field(None, description="User identifier")
    db_id: Optional[str] = Field(None, description="Database / connection identifier")
    chat_id: Optional[str] = Field(None, description="Conversation/chat id")

    last_refined_query: Optional[str] = Field(None, description="Last refined query")
    last_intent: Optional[str] = Field(None, description="Last classified intent")

    last_confirmed_sql: Optional[str] = Field(None, description="Last successful SQL")
    last_tables_used: List[str] = Field(
        default_factory=list, description="Last tables used"
    )
    last_filters: Dict[str, Any] = Field(
        default_factory=dict, description="Last filters as dict"
    )
    last_skeleton_id: Optional[int] = Field(None, description="Optional skeleton id")

    turn_count: int = Field(1, description="Turn count")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    def model_dump(self, *args, **kwargs):
        # By default exclude None values so identifiers are omitted when not set
        if "exclude_none" not in kwargs:
            kwargs["exclude_none"] = True
        return super().model_dump(*args, **kwargs)


def extract_from_state(state: dict[str, Any]) -> SessionContext:
    """Create a SessionContext from the LangGraph state dict.

    This performs best-effort extraction using common state keys.
    """

    # def _parse_dt(val: Any):
    #     if val is None:
    #         return None
    #     if isinstance(val, datetime):
    #         return val
    #     if isinstance(val, str):
    #         try:
    #             # Accept ISO with Z by converting to +00:00
    #             return datetime.fromisoformat(val.replace("Z", "+00:00"))
    #         except Exception:
    #             return None
    #     return None

    # coerce types with sensible defaults
    last_tables = state.get("last_tables_used") or state.get("seed_tables") or []
    if not isinstance(last_tables, list):
        try:
            last_tables = list(last_tables)
        except Exception:
            last_tables = []

    last_filters = state.get("last_filters") or state.get("filters") or {}
    if not isinstance(last_filters, dict):
        last_filters = {}

    turn = state.get("turn_number") or state.get("turn_count") or 1
    try:
        turn = int(turn)
    except Exception:
        turn = 1

    # created = _parse_dt(state.get("created_at")) or datetime.utcnow()
    # updated = _parse_dt(state.get("updated_at")) or datetime.utcnow()

    return SessionContext(
        last_refined_query=(state.get("refined_query") or None),
        last_intent=(
            state.get("intent", {}).get("intent")
            if isinstance(state.get("intent"), dict)
            else None
        ),
        last_confirmed_sql=state.get("generated_sql"),
        last_tables_used=last_tables,
        last_filters=last_filters,
        last_skeleton_id=state.get("last_skeleton_id"),
        turn_count=turn,
    )
