"""
In-Memory Persistent State Store for RAG Pipeline.

Manages three tiers of state across turns:

  PERSISTED   — survives every turn (history, domain_context, credentials, role, last_error_summary)
  CACHED      — survives turns but expires after TTL or topic shift (schema, join_paths, seed_tables)
  EPHEMERAL   — wiped at start of every turn (SQL, validation, execution, errors, planning)

Designed with a thin interface so Redis can be swapped in later with zero
changes to pipeline logic.

Usage:
    store = InMemoryStore()

    # At session start
    store.init_session(session_id, role="analyst", connection={...}, domain_context="sales")

    # At turn start — wipes ephemeral, reloads persisted + cached into a fresh RAGState dict
    state = store.start_turn(session_id, user_query="show me top customers")

    # During the turn — pipeline mutates state normally
    state["generated_sql"] = "SELECT ..."

    # At turn end — extracts and saves what should persist
    store.end_turn(session_id, state)
"""

from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

from src.agent.nodes.state import create_initial_state  # your existing helper

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_CACHE_TTL = 3600  # 1 hour in seconds
MAX_HISTORY_TURNS = 5  # rolling window size

# Keys that are always persisted across turns
PERSISTED_KEYS = {
    "session_id",
    "domain_context",
    "history",
    "role",
    "last_error_summary",
    # DB credentials
    "db_type",
    "server",
    "database",
    "username",
    "password",
    "port",
    # SQL fingerprint (lightweight, not raw SQL)
    "last_sql_tables",
    "last_sql_type",
    "last_sql_status",
}

# Keys that are cached with TTL — stored separately so expiry is easy to check
CACHED_KEYS = {
    "retrieved_schemas",
    "seed_tables",
    "join_paths",
    "schema_coverage",
}

# Everything else in RAGState is ephemeral and gets wiped by start_turn()


# ─────────────────────────────────────────────────────────────────────────────
# Base interface — swap this out for Redis later
# ─────────────────────────────────────────────────────────────────────────────


class StateStore:
    """Abstract interface. Implement this for Redis when ready."""

    def get_persisted(self, session_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def set_persisted(self, session_id: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def get_cached(self, session_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def set_cached(self, session_id: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def invalidate_cache(self, session_id: str) -> None:
        raise NotImplementedError

    def delete_session(self, session_id: str) -> None:
        raise NotImplementedError


# ─────────────────────────────────────────────────────────────────────────────
# In-memory implementation
# ─────────────────────────────────────────────────────────────────────────────


class InMemoryStore(StateStore):
    """
    In-process store. TTL is checked manually on read.
    Replace with RedisStore later — interface is identical.
    """

    def __init__(self):
        # session_id → persisted dict
        self._persisted: Dict[str, Dict[str, Any]] = {}
        # session_id → {"data": {...}, "cached_at": float}
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get_persisted(self, session_id: str) -> Dict[str, Any]:
        return deepcopy(self._persisted.get(session_id, {}))

    def set_persisted(self, session_id: str, data: Dict[str, Any]) -> None:
        self._persisted[session_id] = deepcopy(data)

    def get_cached(self, session_id: str) -> Optional[Dict[str, Any]]:
        entry = self._cache.get(session_id)
        if entry is None:
            return None
        if time.time() - entry["cached_at"] > SCHEMA_CACHE_TTL:
            del self._cache[session_id]
            return None
        return deepcopy(entry["data"])

    def set_cached(self, session_id: str, data: Dict[str, Any]) -> None:
        self._cache[session_id] = {
            "data": deepcopy(data),
            "cached_at": time.time(),
        }

    def invalidate_cache(self, session_id: str) -> None:
        self._cache.pop(session_id, None)

    def delete_session(self, session_id: str) -> None:
        self._persisted.pop(session_id, None)
        self._cache.pop(session_id, None)

    def cache_age_seconds(self, session_id: str) -> Optional[float]:
        """Utility — how old is the schema cache for this session."""
        entry = self._cache.get(session_id)
        if entry is None:
            return None
        return time.time() - entry["cached_at"]

    def list_sessions(self) -> List[str]:
        """Utility — all active session IDs."""
        return list(self._persisted.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Memory Manager — the main API your pipeline calls
# ─────────────────────────────────────────────────────────────────────────────


class MemoryManager:
    """
    Sits between your LangGraph pipeline and the store.

    Pipeline calls:
        manager.init_session(...)   — once at session start
        manager.start_turn(...)     — at the top of every turn
        manager.end_turn(...)       — at the bottom of every turn
    """

    def __init__(self, store: Optional[StateStore] = None):
        self.store = store or InMemoryStore()

    # ── Session lifecycle ────────────────────────────────────────────────────

    def init_session(
        self,
        session_id: str,
        role: str,
        connection: Optional[Dict[str, Any]] = None,
        domain_context: str = "general",
    ) -> None:
        """
        Call once when a user session begins.
        Stores role, credentials, and domain — never re-derives them mid-session.
        """
        conn = connection or {}
        persisted = {
            "session_id": session_id,
            "role": role,
            "domain_context": domain_context,
            "history": [],
            "last_error_summary": None,
            "last_sql_tables": [],
            "last_sql_type": None,
            "last_sql_status": None,
            # credentials
            "db_type": conn.get("db_type"),
            "server": conn.get("server"),
            "database": conn.get("database"),
            "username": conn.get("username"),
            "password": conn.get("password"),
            "port": conn.get("port"),
        }
        self.store.set_persisted(session_id, persisted)

    # ── Turn lifecycle ───────────────────────────────────────────────────────

    def start_turn(
        self,
        session_id: str,
        user_query: str,
        force_schema_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Call at the top of every turn.

        1. Loads persisted state.
        2. Loads schema cache (if valid).
        3. Builds a fresh RAGState dict with ephemeral fields blank.
        4. Returns state dict ready for the pipeline.
        """
        persisted = self.store.get_persisted(session_id)
        if not persisted:
            raise ValueError(
                f"No session found for id '{session_id}'. Call init_session first."
            )

        # Detect topic shift — invalidate schema cache if domain changed
        if force_schema_refresh:
            self.store.invalidate_cache(session_id)

        cached = self.store.get_cached(session_id)

        # Build initial state using your existing helper
        state = create_initial_state(
            user_query=user_query,
            user_role=persisted.get("role") or persisted.get("user_role") or "",
            domain_context=persisted.get("domain_context", "general"),
            history=persisted.get("history", []),
            session_id=session_id,
            connection={
                "db_type": persisted.get("db_type"),
                "server": persisted.get("server"),
                "database": persisted.get("database"),
                "username": persisted.get("username"),
                "password": persisted.get("password"),
                "port": persisted.get("port"),
            },
        )

        # Stamp turn number
        state["turn_number"] = len(persisted.get("history", [])) + 1

        # Inject persisted extras not covered by create_initial_state
        state["role"] = persisted.get("role")
        state["last_error_summary"] = persisted.get("last_error_summary")
        state["last_sql_tables"] = persisted.get("last_sql_tables", [])
        state["last_sql_type"] = persisted.get("last_sql_type")
        state["last_sql_status"] = persisted.get("last_sql_status")

        # Inject cached schema data if available
        if cached:
            state["retrieved_schemas"] = cached.get("retrieved_schemas", [])
            state["seed_tables"] = cached.get("seed_tables", [])
            state["join_paths"] = cached.get("join_paths", [])
            state["schema_coverage"] = cached.get("schema_coverage")

        return state

    def end_turn(
        self,
        session_id: str,
        state: Dict[str, Any],
        assistant_response: Optional[str] = None,
    ) -> None:
        """
        Call at the bottom of every turn.

        1. Appends to rolling history (max 5 turns).
        2. Saves error summary if turn failed.
        3. Saves SQL fingerprint.
        4. Saves schema cache if schemas were freshly fetched.
        """
        persisted = self.store.get_persisted(session_id)

        # ── Rolling history ──────────────────────────────────────────────────
        history: List[Dict[str, str]] = persisted.get("history", [])
        history.append(
            {
                "role": "user",
                "content": state.get("user_query", ""),
            }
        )
        if assistant_response or state.get("user_facing_response"):
            history.append(
                {
                    "role": "assistant",
                    "content": assistant_response
                    or state.get("user_facing_response", ""),
                }
            )
        # Keep last MAX_HISTORY_TURNS complete exchanges (each = 2 entries)
        max_entries = MAX_HISTORY_TURNS * 2
        persisted["history"] = history[-max_entries:]

        # ── Error summary ────────────────────────────────────────────────────
        sql_errors = state.get("sql_errors", [])
        hallucinated = state.get("hallucinated_tables", [])
        validation_errors = state.get("validation_errors", [])

        if sql_errors or hallucinated or validation_errors:
            parts = []
            if hallucinated:
                parts.append(f"hallucinated tables: {', '.join(hallucinated)}")
            if sql_errors:
                parts.append(f"sql errors: {'; '.join(sql_errors[:2])}")
            if validation_errors:
                parts.append(f"validation: {'; '.join(validation_errors[:2])}")
            persisted["last_error_summary"] = " | ".join(parts)
        else:
            persisted["last_error_summary"] = None

        # ── SQL fingerprint ──────────────────────────────────────────────────
        generated_sql = state.get("generated_sql")
        if generated_sql:
            persisted["last_sql_tables"] = _extract_tables_from_state(state)
            persisted["last_sql_type"] = _infer_sql_type(generated_sql)
            persisted["last_sql_status"] = (
                "success"
                if state.get("validation_passed")
                else "retried" if state.get("retry_feedback") else "failed"
            )
        else:
            persisted["last_sql_tables"] = []
            persisted["last_sql_type"] = None
            persisted["last_sql_status"] = None

        self.store.set_persisted(session_id, persisted)

        # ── Schema cache ─────────────────────────────────────────────────────
        # Only update cache if schemas were actually fetched this turn
        if state.get("retrieved_schemas"):
            self.store.set_cached(
                session_id,
                {
                    "retrieved_schemas": state.get("retrieved_schemas", []),
                    "seed_tables": state.get("seed_tables", []),
                    "join_paths": state.get("join_paths", []),
                    "schema_coverage": state.get("schema_coverage"),
                },
            )

    # ── Convenience helpers ──────────────────────────────────────────────────

    def get_role(self, session_id: str) -> Optional[str]:
        return self.store.get_persisted(session_id).get("role")

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        return self.store.get_persisted(session_id).get("history", [])

    def update_domain_context(self, session_id: str, new_context: str) -> None:
        """Call this + force_schema_refresh=True on next start_turn if domain shifts."""
        persisted = self.store.get_persisted(session_id)
        persisted["domain_context"] = new_context
        self.store.set_persisted(session_id, persisted)
        self.store.invalidate_cache(session_id)

    def end_session(self, session_id: str) -> None:
        self.store.delete_session(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def _extract_tables_from_state(state: Dict[str, Any]) -> List[str]:
    """Pull table names from seed_tables or retrieved_schemas."""
    if state.get("seed_tables"):
        return list(state["seed_tables"])
    schemas = state.get("retrieved_schemas", [])
    tables = []
    for s in schemas:
        if isinstance(s, dict):
            tables.extend(s.get("tables", []))
    return tables[:10]  # cap to keep fingerprint small


def _infer_sql_type(sql: str) -> str:
    """Cheaply classify SQL without parsing it."""
    upper = sql.strip().upper()
    if any(k in upper for k in ("GROUP BY", "COUNT(", "SUM(", "AVG(", "MAX(", "MIN(")):
        return "aggregation"
    if "JOIN" in upper:
        return "join"
    if upper.startswith("SELECT"):
        return "select"
    if upper.startswith("INSERT"):
        return "insert"
    if upper.startswith("UPDATE"):
        return "update"
    if upper.startswith("DELETE"):
        return "delete"
    return "other"
