"""
Standalone tests for session context filter handling (no pytest required).
Tests can be run directly: python tests/test_filter_session_standalone.py
"""

import json
from typing import Any, Dict

from src.agent.nodes.query_refiner import (
    _has_session_context,
    _build_session_context_block,
    _build_user_prompt,
    RefineResult,
    RetryFeedback,
)
from src.agent.nodes.sql_generator import _build_filter_context_block
from src.agent.utils.filter_extractor import flatten_filters


def test_session_context_detection():
    """Test _has_session_context helper."""
    print("Testing session context detection...")

    # Test with last_filters
    state = {"last_filters": {"store_id": [{"operator": "=", "value": 5}]}}
    assert _has_session_context(state) is True, "Should detect last_filters"

    # Test with last_intent
    state = {"last_intent": "Get sales by region"}
    assert _has_session_context(state) is True, "Should detect last_intent"

    # Test with last_refined_query
    state = {"last_refined_query": "Show total sales per region"}
    assert _has_session_context(state) is True, "Should detect last_refined_query"

    # Test with last_tables_used
    state = {"last_tables_used": ["sales", "region"]}
    assert _has_session_context(state) is True, "Should detect last_tables_used"

    # Test empty state
    assert _has_session_context({}) is False, "Should return False for empty state"

    # Test with empty values
    state = {
        "last_filters": {},
        "last_intent": "",
        "last_refined_query": "",
        "last_tables_used": [],
    }
    assert _has_session_context(state) is False, "Should return False for empty values"

    print("✓ Session context detection tests passed")


def test_session_context_block_building():
    """Test _build_session_context_block helper."""
    print("Testing session context block building...")

    # Test with all fields
    state = {
        "last_refined_query": "Get total sales per region",
        "last_intent": "Aggregate sales by region",
        "last_filters": {"store_id": [{"operator": "=", "value": 5}]},
        "last_tables_used": ["sales", "region"],
    }
    block = _build_session_context_block(state)
    assert block is not None, "Should build complete session context JSON"
    data = json.loads(block)
    assert "LastQuery" in data
    assert "LastIntent" in data
    assert "LastFiltersApplied" in data
    assert "LastTablesUsed" in data
    print("✓ Built complete session context block")

    # Test with OR filters
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
    print("✓ Correctly handled OR filters in session context")

    # Test returns None for empty state
    assert _build_session_context_block({}) is None
    print("✓ Returns None for empty state")

    print("✓ Session context block building tests passed")


def test_user_prompt_building():
    """Test _build_user_prompt with session context."""
    print("Testing user prompt building...")

    # Test fresh query
    prompt = _build_user_prompt("Show sales", None, None)
    assert prompt == "Show sales", "Fresh query should be unchanged"
    print("✓ Fresh query passed through unchanged")

    # Test with session context
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
    print("✓ Session context injected into prompt")

    # Test with retry feedback
    feedback = RetryFeedback(
        issues=["empty_result"],
        reasoning="WHERE clause filtered all rows",
        failed_sql="SELECT * FROM sales WHERE region='XYZ'",
        hint="Use correct region code",
        attempt=1,
    )
    prompt = _build_user_prompt("Retry the query", feedback, None)
    data = json.loads(prompt)
    assert "RetryContext" in data
    print("✓ Retry feedback included in prompt")

    # Test with both retry and session
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
    print("✓ Both retry and session context included in prompt")

    print("✓ User prompt building tests passed")


def test_filter_context_block_building():
    """Test _build_filter_context_block in sql_generator."""
    print("Testing filter context block building...")

    # Test with simple AND filters
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
    where = carry_forward["WhereClause"]
    assert "store_id = 5" in where
    assert "region = 'North'" in where
    print("✓ Built filter context for AND filters")

    # Test with OR filters
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
    assert "store_id = 5" in where
    assert "OR" in where
    print("✓ Correctly handled OR filters in context block")

    # Test with IN operator
    last_filters = {
        "store_id": [{"operator": "IN", "value": [1, 2, 3]}],
    }
    block = _build_filter_context_block(last_filters)
    assert block is not None
    data = json.loads(block)
    assert "CarryForwardFilters" in data
    print("✓ Handled IN operator in filter context")

    # Test with BETWEEN operator
    last_filters = {
        "amount": [{"operator": "BETWEEN", "value": [100, 500]}],
    }
    block = _build_filter_context_block(last_filters)
    assert block is not None
    data = json.loads(block)
    assert "CarryForwardFilters" in data
    print("✓ Handled BETWEEN operator in filter context")

    # Test returns None for empty
    assert _build_filter_context_block({}) is None
    print("✓ Returns None for empty filters")

    # Test includes Details field with flattened filters
    last_filters = {
        "store_id": [{"operator": "=", "value": 5}],
        "_or": [
            {"category": [{"operator": "=", "value": "vest"}]},
            {"category": [{"operator": "=", "value": "pants"}]},
        ],
    }
    block = _build_filter_context_block(last_filters)
    data = json.loads(block)
    carry_forward = data["CarryForwardFilters"]
    assert "Details" in carry_forward
    details = carry_forward["Details"]
    assert len(details) > 0
    groups = {f["group"] for f in details}
    assert "and" in groups
    assert any(g.startswith("or_") for g in groups)
    print("✓ Correctly flattened filters in Details field")

    print("✓ Filter context block building tests passed")


def test_flatten_filters_with_context():
    """Test flatten_filters with new OR structure."""
    print("Testing flatten_filters with context...")

    # Test simple AND filters
    filters = {
        "store_id": [{"operator": "=", "value": 5}],
        "region": [{"operator": "=", "value": "North"}],
    }
    flattened = flatten_filters(filters)
    assert len(flattened) == 2
    assert all(f["group"] == "and" for f in flattened)
    print("✓ Flattened simple AND filters")

    # Test with OR group
    filters = {
        "store_id": [{"operator": "=", "value": 5}],
        "_or": [
            {"category": [{"operator": "=", "value": "vest"}]},
            {"category": [{"operator": "=", "value": "pants"}]},
        ],
    }
    flattened = flatten_filters(filters)
    assert len(flattened) == 3  # 1 AND + 2 OR

    and_items = [f for f in flattened if f["group"] == "and"]
    assert len(and_items) == 1

    or_items = [f for f in flattened if f["group"].startswith("or_")]
    assert len(or_items) == 2
    or_group_id = or_items[0]["group"]
    assert all(f["group"] == or_group_id for f in or_items)
    print("✓ Preserved OR group identifiers during flattening")

    print("✓ Flatten filters tests passed")


def test_integration():
    """Test complete integration of session context in pipeline."""
    print("\nTesting complete integration...")

    # Simulate a session continuation scenario
    state = {
        "user_query": "Show me more products from this category",
        "history": [],
        "last_refined_query": "Get products from store 5",
        "last_intent": "Browse products",
        "last_filters": {
            "store_id": [{"operator": "=", "value": 5}],
            "category": [{"operator": "=", "value": "Shirts"}],
        },
        "last_tables_used": ["products"],
    }

    # Check that session context is detected
    assert _has_session_context(state), "Should detect session context"
    print("✓ Session context detected")

    # Build session context block
    session_block = _build_session_context_block(state)
    assert session_block is not None
    print("✓ Session context block built")

    # Build user prompt with session context
    prompt = _build_user_prompt(state["user_query"], None, session_block)
    prompt_data = json.loads(prompt)
    assert "CurrentQuery" in prompt_data
    assert "SessionContext" in prompt_data
    print("✓ User prompt built with session context")

    # Build filter context for sql_generator
    filter_block = _build_filter_context_block(state["last_filters"])
    assert filter_block is not None
    filter_data = json.loads(filter_block)
    assert "CarryForwardFilters" in filter_data
    print("✓ Filter context block built for sql_generator")

    # Verify WHERE clause generation
    carry_forward = filter_data["CarryForwardFilters"]
    where = carry_forward["WhereClause"]
    assert "store_id = 5" in where
    assert "category = 'Shirts'" in where
    print("✓ WHERE clause correctly generated with carried filters")

    print("\n✓ Complete integration test passed")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    print("=" * 80)
    print("Running Filter Session Handling Tests")
    print("=" * 80 + "\n")

    try:
        test_session_context_detection()
        print()
        test_session_context_block_building()
        print()
        test_user_prompt_building()
        print()
        test_filter_context_block_building()
        print()
        test_flatten_filters_with_context()
        print()
        test_integration()

        print("\n" + "=" * 80)
        print("✓ ALL TESTS PASSED")
        print("=" * 80)

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
