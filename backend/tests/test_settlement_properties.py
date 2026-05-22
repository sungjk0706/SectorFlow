# -*- coding: utf-8 -*-
"""Property-based tests for the simplified Settlement Engine using Hypothesis."""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.settlement_engine import (
    BUY_COMMISSION, SELL_COMMISSION, SECURITIES_TAX,
    init, get_available_cash, get_accumulated_investment, get_orderable, get_initial_deposit,
    check_buy_power, on_buy_fill, on_sell_fill,
    charge, get_effective_buy_power, reset,
    save_state, restore_state,
)

@pytest.fixture(autouse=True)
def reset_engine_state():
    """Reset settlement engine state before each test."""
    init(10_000_000)  # 1천만원 초기 예수금
    yield
    init(0)


# ── Property 1: Buy fill deduction is exact and preserves non-negativity ────

@given(
    price=st.integers(min_value=100, max_value=1_000_000),
    qty=st.integers(min_value=1, max_value=1000),
    initial=st.integers(min_value=1, max_value=1_000_000_000),
)
@settings(max_examples=100, deadline=None)
def test_buy_fill_deduction(price, qty, initial):
    """Property 1: Buy fill deduction is exact and preserves non-negativity."""
    init(initial)
    cost = price * qty + round(price * qty * BUY_COMMISSION)
    assume(cost <= initial)  # Only test valid buys
    
    result = on_buy_fill(price, qty)
    
    assert result == initial - cost
    assert result >= 0
    assert get_available_cash() == result
    assert get_orderable() == result
    # Accumulated investment must remain unchanged
    assert get_accumulated_investment() == initial


# ── Property 2: Buy power check correctly enforces effective limit ───────────

@given(
    available=st.integers(min_value=0, max_value=100_000_000),
    daily_limit=st.integers(min_value=0, max_value=100_000_000),
    daily_spent=st.integers(min_value=0, max_value=100_000_000),
    order_amount=st.integers(min_value=1, max_value=50_000_000),
)
@settings(max_examples=100)
def test_buy_power_check(available, daily_limit, daily_spent, order_amount):
    """Property 2: Buy power check correctly enforces effective limit."""
    init(available)
    cost = order_amount + round(order_amount * BUY_COMMISSION)
    effective = get_effective_buy_power(daily_limit, daily_spent)
    
    ok, reason = check_buy_power(order_amount, daily_limit, daily_spent)
    if cost > effective:
        assert ok is False
        assert reason != ""
    else:
        assert ok is True
        assert reason == ""


# ── Property 3: Sell fill adds net proceeds correctly ────────────────────────

@given(
    price=st.integers(min_value=100, max_value=1_000_000),
    qty=st.integers(min_value=1, max_value=1000),
    initial=st.integers(min_value=0, max_value=1_000_000_000),
)
@settings(max_examples=100)
def test_sell_fill_proceeds(price, qty, initial):
    """Property 3: Sell fill adds net proceeds correctly."""
    init(initial)
    gross = price * qty
    expected_net = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
    
    result = on_sell_fill(price, qty, "005930", "삼성전자")
    
    assert result == initial + expected_net
    assert get_available_cash() == result
    assert get_orderable() == result
    # Accumulated investment must remain unchanged
    assert get_accumulated_investment() == initial


# ── Property 4: Charge increases both available cash and accumulated investment ──

@given(
    initial=st.integers(min_value=0, max_value=1_000_000_000),
    charge_amount=st.integers(min_value=1, max_value=100_000_000),
)
@settings(max_examples=100)
def test_charge_exact(initial, charge_amount):
    """Property 4: Charge increases both orderable cash and accumulated investment."""
    init(initial)
    
    result = charge(charge_amount)
    
    assert result == initial + charge_amount
    assert get_available_cash() == initial + charge_amount
    assert get_orderable() == initial + charge_amount
    assert get_accumulated_investment() == initial + charge_amount


# ── Property 5: Reset restores initial state completely ──────────────────────

@given(
    initial=st.integers(min_value=1_000_000, max_value=1_000_000_000),
    new_initial=st.integers(min_value=1_000_000, max_value=1_000_000_000),
)
@settings(max_examples=100)
def test_reset_restores_initial(initial, new_initial):
    """Property 5: Reset restores initial state completely."""
    init(initial)
    on_sell_fill(10000, 10, "005930", "삼성전자")
    on_buy_fill(5000, 20)
    
    reset(new_initial)
    
    assert get_available_cash() == new_initial
    assert get_orderable() == new_initial
    assert get_accumulated_investment() == new_initial
    assert get_initial_deposit() == new_initial


# ── Property 6: State persistence round-trip ─────────────────────────────────

def test_persistence_round_trip():
    """Property 6: State persistence round-trip."""
    init(50_000_000)
    on_sell_fill(10000, 100, "005930", "삼성전자")
    
    available_before = get_available_cash()
    accumulated_before = get_accumulated_investment()
    initial_before = get_initial_deposit()
    
    # Save
    save_state()
    
    # Dirty state in memory
    init(0)
    assert get_available_cash() == 0
    assert get_accumulated_investment() == 0
    
    # Restore
    restore_state()
    
    assert get_available_cash() == available_before
    assert get_accumulated_investment() == accumulated_before
    assert get_initial_deposit() == initial_before
