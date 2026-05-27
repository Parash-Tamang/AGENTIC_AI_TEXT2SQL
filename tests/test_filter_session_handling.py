"""
Tests for session context filter handling in query_refiner and sql_generator.

Validates:
1. query_refiner detects and injects session context with last_filters
2. sql_generator builds proper filter context blocks
3. OR filters are correctly handled in both nodes
4. CONTINUE vs FRESH classification logic
"""

import json
from unittest.mock import MagicMock, patch
from typing import Any, Dict

import pytest

from src.agent.nodes.query_refiner import (
    query_refiner,
    _has_session_context,
    _build_session_context_block,
    _build_user_prompt,
    RefineResult,
)
from src.agent.nodes.sql_generator import _build_filter_context_block
from src.agent.utils.filter_extractor import flatten_filters

# ─────────────────────────────────────────────────────────────────────────────
# Test: Session Context Detection
# ─────────────────────────────────────────────────────────────────────────────


class TestSessionContextDetection:
    """Test _has_session_context helper."""

    def test_has_session_context_with_last_filters(self):
        """Should detect session context when last_filters present."""
        state = {"last_filters": {"store_id": [{"operator": "=", "value": 5}]}}
        assert _has_session_context(state) is True

    def test_has_session_context_with_last_intent(self):
        """Should detect session context when last_intent present."""
        state = {"last_intent": "Get sales by region"}
        assert _has_session_context(state) is True

    def test_has_session_context_with_last_refined_query(self):
        """Should detect session context when last_refined_query present."""
        state = {"last_refined_query": "Show total sales per region"}
        assert _has_session_context(state) is True

    def test_has_session_context_with_last_tables(self):
        """Should detect session context when last_tables_used present."""
        state = {"last_tables_used": ["sales", "region"]}
        assert _has_session_context(state) is True

    def test_no_session_context_empty_state(self):
        """Should return False for empty state."""
        state = {}
        assert _has_session_context(state) is False

    def test_no_session_context_empty_values(self):
        """Should return False when all session fields are empty."""
        state = {
            "last_filters": {},
            "last_intent": "",
            "last_refined_query": "",
            "last_tables_used": [],
        }
        assert _has_session_context(state) is False


# ─────────────────────────────────────────────────────────────────────────────
# Test: Session Context Block Building
# ─────────────────────────────────────────────────────────────────────────────


class TestSessionContextBlockBuilding:
    """Test _build_session_context_block helper."""

    def test_build_session_context_with_all_fields(self):
        """Should build complete session context JSON."""
        state = {
            "last_refined_query": "Get total sales per region",
            "last_intent": "Aggregate sales by region",
            "last_filters": {"store_id": [{"operator": "=", "value": 5}]},
            "last_tables_used": ["sales", "region"],
        }
        block = _build_session_context_block(state)
        assert block is not None
        data = json.loads(block)
        assert "LastQuery" in data
        assert "LastIntent" in data
        assert "LastFiltersApplied" in data
        assert "LastTablesUsed" in data
        assert data["LastQuery"] == "Get total sales per region"
        assert data["LastIntent"] == "Aggregate sales by region"

    def test_build_session_context_with_or_filters(self):
        """Should include complex OR filter structure."""
        state = {
            "last_refined_query": "Find products",
            "last_filters": {
                "store_id": [{"operator": "=", "value": 5}],
                "_or": [
                    {"category": [{"operator": "=", "value": "vest"}]},
                    {"category": [{"operator": "=", "value": "pants"}]},
                ],
            },
        }
        block = _build_session_context_block(state)
        assert block is not None
        data = json.loads(block)
        filters = data["LastFiltersApplied"]
        assert "store_id" in filters
        assert "_or" in filters
        assert len(filters["_or"]) == 2

    def test_build_session_context_returns_none_for_empty_state(self):
        """Should return None when no meaningful context exists."""
        state = {}
        block = _build_session_context_block(state)
        assert block is None

    def test_build_session_context_returns_none_for_empty_values(self):
        """Should return None when all session fields are empty."""
        state = {
            "last_refined_query": "",
            "last_intent": "",
            "last_filters": {},
            "last_tables_used": [],
        }
        block = _build_session_context_block(state)
        assert block is None


# ─────────────────────────────────────────────────────────────────────────────
# Test: User Prompt Building with Session Context
# ─────────────────────────────────────────────────────────────────────────────


class TestUserPromptBuilding:
    """Test _build_user_prompt with session context."""

    def test_build_user_prompt_fresh_query(self):
        """Fresh query with no session context."""
        prompt = _build_user_prompt("Show sales", None, None)
        assert prompt == "Show sales"

    def test_build_user_prompt_with_session_context(self):
        """Should include session context in prompt."""
        user_query = "Show more details"
        session_block = json.dumps(
            {
                "LastQuery": "Previous query",
                "LastIntent": "Get sales",
                "LastFiltersApplied": {"store_id": [{"operator": "=", "value": 5}]},
            }
        )
        prompt = _build_user_prompt(user_query, None, session_block)
        data = json.loads(prompt)
        assert "CurrentQuery" in data
        assert "SessionContext" in data
        assert data["CurrentQuery"] == user_query

    def test_build_user_prompt_with_retry_feedback(self):
        """Should include retry feedback in prompt."""
        from src.agent.nodes.query_refiner import RetryFeedback

        user_query = "Retry the query"
        feedback = RetryFeedback(
            issues=["empty_result"],
            reasoning="WHERE clause filtered all rows",
            failed_sql="SELECT * FROM sales WHERE region='XYZ'",
            hint="Use correct region code",
            attempt=1,
        )
        prompt = _build_user_prompt(user_query, feedback, None)
        data = json.loads(prompt)
        assert "RetryContext" in data
        assert data["RetryContext"]["issues"] == ["empty_result"]
        assert data["RetryContext"]["attempt"] == 1

    def test_build_user_prompt_with_both_retry_and_session(self):
        """Should include both retry feedback and session context."""
        from src.agent.nodes.query_refiner import RetryFeedback

        feedback = RetryFeedback(
            issues=["empty_result"],
            reasoning="WHERE filtered all",
            failed_sql="SELECT * FROM sales",
            hint="Fix the filter",
            attempt=2,
        )
        session_block = json.dumps(
            {
                "LastQuery": "Previous query",
                "LastFiltersApplied": {"store_id": [{"operator": "=", "value": 5}]},
            }
        )
        prompt = _build_user_prompt("Retry", feedback, session_block)
        data = json.loads(prompt)
        assert "RetryContext" in data
        assert "SessionContext" in data


# ─────────────────────────────────────────────────────────────────────────────
# Test: Filter Context Block Building (SQL Generator)
# ─────────────────────────────────────────────────────────────────────────────


class TestFilterContextBlockBuilding:
    """Test _build_filter_context_block in sql_generator."""

    def test_build_filter_context_with_simple_and_filters(self):
        """Should build filter context for simple AND filters."""
        last_filters = {
            "store_id": [{"operator": "=", "value": 5}],
            "region": [{"operator": "=", "value": "North"}],
        }
        block = _build_filter_context_block(last_filters)
        assert block is not None
        data = json.loads(block)
        assert "CarryForwardFilters" in data
        carry_forward = data["CarryForwardFilters"]
        assert "WhereClause" in carry_forward
        # Should contain both filters
        where = carry_forward["WhereClause"]
        assert "store_id = 5" in where
        assert "region = 'North'" in where

    def test_build_filter_context_with_or_filters(self):
        """Should correctly handle OR filters in context block."""
        last_filters = {
            "store_id": [{"operator": "=", "value": 5}],
            "_or": [
                {"category": [{"operator": "=", "value": "vest"}]},
                {"category": [{"operator": "=", "value": "pants"}]},
            ],
        }
        block = _build_filter_context_block(last_filters)
        assert block is not None
        data = json.loads(block)
        carry_forward = data["CarryForwardFilters"]
        where = carry_forward["WhereClause"]

        # Should have AND and OR parts
        assert "store_id = 5" in where
        assert "OR" in where
        assert "category" in where

    def test_build_filter_context_with_in_operator(self):
        """Should handle IN operator in filter context."""
        last_filters = {
            "store_id": [
                {"operator": "IN", "value": [1, 2, 3]},
            ],
        }
        block = _build_filter_context_block(last_filters)
        assert block is not None
        data = json.loads(block)
        carry_forward = data["CarryForwardFilters"]
        where = carry_forward["WhereClause"]
        assert "store_id" in where
        assert "IN" in where

    def test_build_filter_context_with_between_operator(self):
        """Should handle BETWEEN operator in filter context."""
        last_filters = {
            "amount": [
                {"operator": "BETWEEN", "value": [100, 500]},
            ],
        }
        block = _build_filter_context_block(last_filters)
        assert block is not None
        data = json.loads(block)
        carry_forward = data["CarryForwardFilters"]
        where = carry_forward["WhereClause"]
        assert "amount" in where

    def test_build_filter_context_returns_none_for_empty(self):
        """Should return None for empty filters."""
        assert _build_filter_context_block({}) is None
        assert _build_filter_context_block(None) is None

    def test_build_filter_context_details_field(self):
        """Should include flattened filter details."""
        last_filters = {
            "store_id": [{"operator": "=", "value": 5}],
            "_or": [
                {"category": [{"operator": "=", "value": "vest"}]},
                {"category": [{"operator": "=", "value": "pants"}]},
            ],
        }
        block = _build_filter_context_block(last_filters)
        assert block is not None
        data = json.loads(block)
        carry_forward = data["CarryForwardFilters"]

        # Details should be flattened filter list
        assert "Details" in carry_forward
        details = carry_forward["Details"]
        assert len(details) > 0

        # Check that AND and OR filters are properly grouped
        groups = {f["group"] for f in details}
        assert "and" in groups
        assert any(g.startswith("or_") for g in groups)


# ─────────────────────────────────────────────────────────────────────────────
# Test: Flatten Filters with Session Context
# ─────────────────────────────────────────────────────────────────────────────


class TestFlattenFiltersWithContext:
    """Test flatten_filters with new OR structure."""

    def test_flatten_simple_and_filters(self):
        """Should flatten simple AND filters."""
        filters = {
            "store_id": [{"operator": "=", "value": 5}],
            "region": [{"operator": "=", "value": "North"}],
        }
        flattened = flatten_filters(filters)
        assert len(flattened) == 2
        assert all(f["group"] == "and" for f in flattened)

    def test_flatten_with_or_group(self):
        """Should preserve OR group identifiers during flattening."""
        filters = {
            "store_id": [{"operator": "=", "value": 5}],
            "_or": [
                {"category": [{"operator": "=", "value": "vest"}]},
                {"category": [{"operator": "=", "value": "pants"}]},
            ],
        }
        flattened = flatten_filters(filters)

        # Should have 3 items: 1 AND + 2 OR
        assert len(flattened) == 3

        # First should be AND
        and_items = [f for f in flattened if f["group"] == "and"]
        assert len(and_items) == 1
        assert and_items[0]["column"] == "store_id"

        # Others should be OR with same group ID
        or_items = [f for f in flattened if f["group"].startswith("or_")]
        assert len(or_items) == 2
        or_group_id = or_items[0]["group"]
        assert all(f["group"] == or_group_id for f in or_items)

    def test_flatten_multiple_or_groups(self):
        """Should handle multiple OR groups separately."""
        filters = {
            "_or": [
                {"category": [{"operator": "=", "value": "vest"}]},
                {"category": [{"operator": "=", "value": "pants"}]},
            ],
            "_or_2": [
                {"color": [{"operator": "=", "value": "red"}]},
                {"color": [{"operator": "=", "value": "blue"}]},
            ],
        }
        flattened = flatten_filters(filters)

        # Should have 4 items grouped separately
        assert len(flattened) == 4

        # Group IDs should be different for each OR set
        groups = {f["group"] for f in flattened}
        # Should have at least 2 different OR groups
        or_groups = [g for g in groups if g.startswith("or_")]
        assert len(or_groups) >= 2


# ─────────────────────────────────────────────────────────────────────────────
# Test: Query Refiner Integration
# ─────────────────────────────────────────────────────────────────────────────


class TestQueryRefinerIntegration:
    """Integration tests for query_refiner with session context."""

    @patch("src.agent.nodes.query_refiner.BaseLLM")
    def test_query_refiner_with_session_context(self, mock_llm_class):
        """Should inject session context into LLM call."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = json.dumps(
            {
                "Classification": "CONTINUE",
                "Confidence": 0.95,
                "ConstructedQuery": "Show products in this category",
                "Reasoning": "Continuing from previous query with existing filters",
            }
        )

        state = {
            "user_query": "Show products",
            "history": [],
            "last_refined_query": "Get products by region",
            "last_intent": "Filter products",
            "last_filters": {"store_id": [{"operator": "=", "value": 5}]},
            "last_tables_used": ["products"],
        }

        result = query_refiner(llm=mock_llm, state=state)

        # Verify LLM was called
        assert mock_llm.generate.called

        # Extract the user_prompt that was passed to LLM
        call_args = mock_llm.generate.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args.args[1]

        # Verify session context was included
        prompt_data = json.loads(user_prompt)
        assert "SessionContext" in prompt_data
        assert prompt_data["SessionContext"]["LastQuery"] == "Get products by region"

    @patch("src.agent.nodes.query_refiner.BaseLLM")
    def test_query_refiner_without_session_context(self, mock_llm_class):
        """Should not inject session context for FRESH queries."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = json.dumps(
            {
                "Classification": "FRESH",
                "Confidence": 0.98,
                "ConstructedQuery": "Get sales data",
                "Reasoning": "Fresh query with no prior context",
            }
        )

        state = {
            "user_query": "Get sales data",
            "history": [],
        }

        result = query_refiner(llm=mock_llm, state=state)

        # Verify LLM was called
        assert mock_llm.generate.called

        # Extract the user_prompt
        call_args = mock_llm.generate.call_args
        user_prompt = call_args.kwargs.get("user_prompt") or call_args.args[1]

        # For fresh query, prompt should be the query itself
        assert user_prompt == "Get sales data" or "SessionContext" not in user_prompt


# ─────────────────────────────────────────────────────────────────────────────
# Test: SQL Generator Filter Integration
# ─────────────────────────────────────────────────────────────────────────────


class TestSQLGeneratorFilterIntegration:
    """Test sql_generator with carry-forward filters."""

    def test_sql_generator_builds_filter_context(self):
        """sql_generator should build filter context from last_filters."""
        last_filters = {
            "store_id": [{"operator": "=", "value": 5}],
            "region": [{"operator": "=", "value": "North"}],
        }

        block = _build_filter_context_block(last_filters)

        # Should produce valid JSON with CarryForwardFilters
        assert block is not None
        data = json.loads(block)
        assert "CarryForwardFilters" in data

        # Should have instruction
        carry_forward = data["CarryForwardFilters"]
        assert "Instruction" in carry_forward
        assert "Apply these filters" in carry_forward["Instruction"]


# ─────────────────────────────────────────────────────────────────────────────
# Main execution
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
