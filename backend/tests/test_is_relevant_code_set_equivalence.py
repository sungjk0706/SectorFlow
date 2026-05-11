# -*- coding: utf-8 -*-
"""Property-based test: _is_relevant_code Set Equivalence (Property 8).

Feature: hts-level-optimization, Property 8: set 캐시 정확성

Validates that the set-based _is_relevant_code implementation produces
the same boolean result as a naive list-traversal approach for any
stock code and any state of _positions / _sector_stock_layout.

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
from app.services import engine_account_notify as ean


# ── Strategies ───────────────────────────────────────────────────────────────

# Generate realistic 6-digit stock codes (Korean market style)
stock_code_strategy = st.from_regex(r"[0-9]{6}", fullmatch=True)

# Generate stock codes with various formats (A prefix, _AL/_NX suffix, short codes)
raw_stock_code_strategy = st.one_of(
    stock_code_strategy,
    stock_code_strategy.map(lambda c: f"A{c}"),
    stock_code_strategy.map(lambda c: f"{c}_AL"),
    stock_code_strategy.map(lambda c: f"{c}_NX"),
    st.from_regex(r"[0-9]{1,5}", fullmatch=True),  # short codes (will be zero-padded)
)

# Generate a position dict with stk_cd field
position_strategy = st.fixed_dictionaries({
    "stk_cd": raw_stock_code_strategy,
    "qty": st.integers(min_value=0, max_value=10000),
})

# Generate a layout tuple (type, value)
layout_entry_strategy = st.one_of(
    st.tuples(st.just("code"), stock_code_strategy),
    st.tuples(st.just("header"), st.text(min_size=1, max_size=10)),
    st.tuples(st.just("separator"), st.just("")),
)


# ── Reference (list-traversal) implementation ────────────────────────────────

def _is_relevant_code_list_traversal(
    nk: str,
    pending_stock_details: dict,
    positions: list[dict],
    layout: list[tuple[str, str]],
) -> bool:
    """Original list-traversal approach (O(n)) for comparison."""
    if nk in pending_stock_details:
        return True
    # List traversal over positions
    if any(
        _format_kiwoom_reg_stk_cd(str(p.get("stk_cd", ""))) == nk
        for p in positions
    ):
        return True
    # List traversal over layout
    if any(v == nk for t, v in layout if t == "code"):
        return True
    return False


# ── Property 8: _is_relevant_code Set Equivalence ────────────────────────────


@given(
    query_code=raw_stock_code_strategy,
    positions=st.lists(position_strategy, min_size=0, max_size=50),
    layout=st.lists(layout_entry_strategy, min_size=0, max_size=30),
    pending_codes=st.lists(stock_code_strategy, min_size=0, max_size=20),
)
@settings(max_examples=200, deadline=None)
def test_is_relevant_code_set_equivalence(
    query_code: str,
    positions: list[dict],
    layout: list[tuple[str, str]],
    pending_codes: list[str],
):
    """Property 8: set-based _is_relevant_code === list-traversal result.

    For any stock code and any state of _positions and _sector_stock_layout,
    the set-based _is_relevant_code SHALL return the same boolean result
    as the original list-traversal implementation.

    **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5**
    """
    import app.services.engine_service as _es

    # Normalize the query code the same way _is_relevant_code does
    nk = _format_kiwoom_reg_stk_cd(query_code)

    # Build pending_stock_details dict
    pending_stock_details = {code: {"status": "active"} for code in pending_codes}

    # Save original state
    original_pending = _es._pending_stock_details
    original_positions_set = ean._positions_code_set
    original_layout_set = ean._layout_code_set

    try:
        # Set up the state
        _es._pending_stock_details = pending_stock_details

        # Rebuild set caches (the optimized path)
        ean._rebuild_positions_cache(positions)
        ean._rebuild_layout_cache(layout)

        # Get result from set-based implementation
        set_result = ean._is_relevant_code(nk)

        # Get result from list-traversal reference implementation
        list_result = _is_relevant_code_list_traversal(
            nk, pending_stock_details, positions, layout
        )

        # Property: both must agree
        assert set_result == list_result, (
            f"Set-based and list-traversal disagree for code '{nk}': "
            f"set={set_result}, list={list_result}, "
            f"positions_codes={[_format_kiwoom_reg_stk_cd(str(p.get('stk_cd', ''))) for p in positions]}, "
            f"layout_codes={[v for t, v in layout if t == 'code']}, "
            f"pending_codes={list(pending_stock_details.keys())}"
        )
    finally:
        # Restore original state
        _es._pending_stock_details = original_pending
        ean._positions_code_set = original_positions_set
        ean._layout_code_set = original_layout_set


@given(
    positions=st.lists(position_strategy, min_size=1, max_size=50),
)
@settings(max_examples=100, deadline=None)
def test_positions_code_set_contains_all_normalized_codes(
    positions: list[dict],
):
    """Verify _positions_code_set contains exactly the normalized stk_cd values from positions.

    **Validates: Requirements 9.1, 9.3**
    """
    original_set = ean._positions_code_set
    try:
        ean._rebuild_positions_cache(positions)

        # Expected: set of all normalized stk_cd values (excluding empty)
        expected = {
            _format_kiwoom_reg_stk_cd(str(p.get("stk_cd", "")))
            for p in positions
            if str(p.get("stk_cd", "")).strip()
        }

        assert ean._positions_code_set == expected, (
            f"_positions_code_set mismatch: "
            f"got={ean._positions_code_set}, expected={expected}"
        )
    finally:
        ean._positions_code_set = original_set


@given(
    layout=st.lists(layout_entry_strategy, min_size=1, max_size=30),
)
@settings(max_examples=100, deadline=None)
def test_layout_code_set_contains_all_code_entries(
    layout: list[tuple[str, str]],
):
    """Verify _layout_code_set contains exactly the values where type=='code'.

    **Validates: Requirements 9.2, 9.3**
    """
    original_set = ean._layout_code_set
    try:
        ean._rebuild_layout_cache(layout)

        # Expected: set of values where type is "code" and value is non-empty
        expected = {v for t, v in layout if t == "code" and v}

        assert ean._layout_code_set == expected, (
            f"_layout_code_set mismatch: "
            f"got={ean._layout_code_set}, expected={expected}"
        )
    finally:
        ean._layout_code_set = original_set


@given(
    query_code=stock_code_strategy,
)
@settings(max_examples=100, deadline=None)
def test_is_relevant_code_returns_false_when_all_empty(
    query_code: str,
):
    """When all caches are empty, _is_relevant_code returns False.

    **Validates: Requirements 9.4, 9.5**
    """
    import app.services.engine_service as _es

    nk = _format_kiwoom_reg_stk_cd(query_code)

    original_pending = _es._pending_stock_details
    original_positions_set = ean._positions_code_set
    original_layout_set = ean._layout_code_set

    try:
        _es._pending_stock_details = {}
        ean._positions_code_set = set()
        ean._layout_code_set = set()

        result = ean._is_relevant_code(nk)
        assert result is False, (
            f"Expected False for code '{nk}' with all empty caches, got {result}"
        )
    finally:
        _es._pending_stock_details = original_pending
        ean._positions_code_set = original_positions_set
        ean._layout_code_set = original_layout_set
