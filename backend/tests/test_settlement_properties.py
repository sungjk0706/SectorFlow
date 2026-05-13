# -*- coding: utf-8 -*-
"""Property-based tests for Settlement Engine using Hypothesis."""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from datetime import date, timedelta

from app.services.settlement_engine import (
    BUY_COMMISSION, SELL_COMMISSION, SECURITIES_TAX,
    _calc_settlement_date, init, get_available_cash, get_withdrawable_cash, get_pending_withdrawal_total,
    get_pending_withdrawals, check_buy_power, on_buy_fill, on_sell_fill,
    charge, withdraw, get_effective_buy_power, reset,
)
from app.core.trading_calendar import is_krx_holiday


@pytest.fixture(autouse=True)
def reset_state():
    """Reset settlement engine state before each test."""
    init(100_000_000)  # 1억원 초기 예수금
    yield
    init(0)


# ── Property 1: Buy fill deduction is exact and preserves non-negativity ────
# Validates: Requirements 1.2, 1.4

@given(
    price=st.integers(min_value=100, max_value=1_000_000),
    qty=st.integers(min_value=1, max_value=1000),
    initial=st.integers(min_value=1, max_value=1_000_000_000),
)
@settings(max_examples=100, deadline=None)
def test_buy_fill_deduction(price, qty, initial):
    """Property 1: Buy fill deduction is exact and preserves non-negativity.

    **Validates: Requirements 1.2, 1.4**
    """
    init(initial)
    cost = price * qty + round(price * qty * BUY_COMMISSION)
    assume(cost <= initial)  # Only test valid buys
    result = on_buy_fill(price, qty)
    assert result == initial - cost
    assert result >= 0
    assert get_available_cash() == result


# ── Property 2: Buy power check correctly enforces effective limit ───────────
# Validates: Requirements 1.3, 3.1, 3.2, 3.3

@given(
    available=st.integers(min_value=0, max_value=100_000_000),
    daily_limit=st.integers(min_value=0, max_value=100_000_000),
    daily_spent=st.integers(min_value=0, max_value=100_000_000),
    order_amount=st.integers(min_value=1, max_value=50_000_000),
)
@settings(max_examples=100)
def test_buy_power_check(available, daily_limit, daily_spent, order_amount):
    """Property 2: Buy power check correctly enforces effective limit.

    **Validates: Requirements 1.3, 3.1, 3.2, 3.3**
    """
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


# ── Property 3: Sell fill adds correct net proceeds and creates matching pending withdrawal ──
# Validates: Requirements 2.1, 2.2, 2.5

@given(
    price=st.integers(min_value=100, max_value=1_000_000),
    qty=st.integers(min_value=1, max_value=1000),
    initial=st.integers(min_value=0, max_value=1_000_000_000),
)
@settings(max_examples=100)
def test_sell_fill_proceeds(price, qty, initial):
    """Property 3: Sell fill adds correct net proceeds and creates matching pending withdrawal.

    **Validates: Requirements 2.1, 2.2, 2.5**
    """
    init(initial)
    gross = price * qty
    expected_net = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
    result = on_sell_fill(price, qty, "005930", "삼성전자")
    assert result == initial + expected_net
    assert get_available_cash() == result
    pws = get_pending_withdrawals()
    assert len(pws) == 1
    assert pws[0]["amount"] == expected_net
    assert pws[0]["stk_cd"] == "005930"


# ── Property 4: Withdrawable cash invariant ──────────────────────────────────
# Validates: Requirements 2.3

@given(
    initial=st.integers(min_value=10_000_000, max_value=1_000_000_000),
    sell_count=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_withdrawable_cash_invariant(initial, sell_count):
    """Property 4: Withdrawable cash invariant.

    **Validates: Requirements 2.3**
    """
    init(initial)
    for i in range(sell_count):
        on_sell_fill(10000, 10, f"00{i:04d}", f"종목{i}")
    # Invariant: withdrawable = available - sum(pending)
    assert get_withdrawable_cash() == get_available_cash() - get_pending_withdrawal_total()


# ── Property 5: Settlement removes pending withdrawal and increases withdrawable cash ──
# Validates: Requirements 2.4

def test_settlement_removes_pending():
    """Property 5: Settlement removes pending withdrawal and increases withdrawable cash.

    **Validates: Requirements 2.4**
    """
    init(10_000_000)
    on_sell_fill(10000, 100, "005930", "삼성전자")
    pw_before = get_pending_withdrawals()
    assert len(pw_before) == 1
    available_before = get_available_cash()
    withdrawable_before = get_withdrawable_cash()
    pw_amount = pw_before[0]["amount"]
    # Simulate settlement callback
    from app.services.settlement_engine import _settle_callback, _pending_withdrawals
    _settle_callback(_pending_withdrawals[0])
    assert len(get_pending_withdrawals()) == 0
    assert get_available_cash() == available_before  # unchanged
    assert get_withdrawable_cash() == available_before  # now fully withdrawable
    assert get_withdrawable_cash() == withdrawable_before + pw_amount


# ── Property 6: D+2 settlement date skips non-business days ─────────────────
# Validates: Requirements 4.1, 4.2

@given(d=st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31)))
@settings(max_examples=200)
def test_d2_skips_holidays(d):
    """Property 6: D+2 settlement date skips non-business days.

    **Validates: Requirements 4.1, 4.2**
    """
    result = _calc_settlement_date(d)
    # Result must be a business day
    assert not is_krx_holiday(result)
    # Result must be at least 2 days after sell_date
    assert result > d
    # Count business days between d and result (exclusive of d, inclusive of result)
    biz_count = 0
    check = d + timedelta(days=1)
    while check <= result:
        if not is_krx_holiday(check):
            biz_count += 1
        check += timedelta(days=1)
    assert biz_count == 2


# ── Property 7: State persistence round-trip with expired entry cleanup ──────
# Validates: Requirements 2.7, 7.3

def test_persistence_round_trip():
    """Property 7: State persistence round-trip with expired entry cleanup.

    **Validates: Requirements 2.7, 7.3**
    """
    init(50_000_000)
    on_sell_fill(10000, 100, "005930", "삼성전자")
    on_sell_fill(20000, 50, "000660", "SK하이닉스")
    available_before = get_available_cash()
    pending_before = get_pending_withdrawals()
    # Persist
    from app.services.settlement_engine import _persist, _load
    _persist()
    # Reset and reload
    init(0)
    assert get_available_cash() == 0
    _load()
    # Should restore (pending items are future-dated so they survive)
    assert get_available_cash() == available_before
    assert len(get_pending_withdrawals()) == len(pending_before)


# ── Property 8: Reset restores initial state completely ──────────────────────
# Validates: Requirements 5.1, 5.2

@given(
    initial=st.integers(min_value=1_000_000, max_value=1_000_000_000),
    new_initial=st.integers(min_value=1_000_000, max_value=1_000_000_000),
)
@settings(max_examples=100)
def test_reset_restores_initial(initial, new_initial):
    """Property 8: Reset restores initial state completely.

    **Validates: Requirements 5.1, 5.2**
    """
    init(initial)
    on_sell_fill(10000, 10, "005930", "삼성전자")
    on_buy_fill(5000, 20)
    # State is now dirty
    reset(new_initial)
    assert get_available_cash() == new_initial
    assert get_pending_withdrawals() == []
    assert get_pending_withdrawal_total() == 0


# ── Property 9: Charge increases Available_Cash by exact amount ──────────────
# Validates: Requirements 1.6, 8.1

@given(
    initial=st.integers(min_value=0, max_value=1_000_000_000),
    charge_amount=st.integers(min_value=1, max_value=100_000_000),
)
@settings(max_examples=100)
def test_charge_exact(initial, charge_amount):
    """Property 9: Charge increases Available_Cash by exact amount.

    **Validates: Requirements 1.6, 8.1**
    """
    init(initial)
    result = charge(charge_amount)
    assert result == initial + charge_amount
    assert get_available_cash() == initial + charge_amount


# ── Property 10: Withdrawal bounded by withdrawable cash ─────────────────────
# Validates: Requirements 8.3, 8.4

@given(
    initial=st.integers(min_value=10_000_000, max_value=1_000_000_000),
    withdraw_amount=st.integers(min_value=1, max_value=500_000_000),
)
@settings(max_examples=100)
def test_withdrawal_bounded(initial, withdraw_amount):
    """Property 10: Withdrawal bounded by withdrawable cash.

    **Validates: Requirements 8.3, 8.4**
    """
    init(initial)
    on_sell_fill(10000, 100, "005930", "삼성전자")  # Creates pending withdrawal
    withdrawable = get_withdrawable_cash()
    success, balance = withdraw(withdraw_amount)
    if withdraw_amount <= withdrawable:
        assert success is True
        assert balance == get_available_cash()
        assert get_available_cash() >= 0
    else:
        assert success is False
        # Balance unchanged
        expected = initial + (10000 * 100 - round(10000 * 100 * SECURITIES_TAX) - round(10000 * 100 * SELL_COMMISSION))
        assert get_available_cash() == expected


# ── Property 11: Mode isolation — test operations do not affect saved state ──
# Validates: Requirements 7.2, 7.3, 7.5

def test_mode_isolation():
    """Property 11: Mode isolation — test operations do not affect saved real state.

    **Validates: Requirements 7.2, 7.3, 7.5**
    """
    init(50_000_000)
    on_sell_fill(10000, 100, "005930", "삼성전자")
    saved_available = get_available_cash()
    saved_pending_count = len(get_pending_withdrawals())
    # Save state (simulating test→real switch: persist before leaving)
    from app.services.settlement_engine import save_state, restore_state
    save_state()
    # Simulate being in real mode: clear in-memory state (real mode doesn't use settlement engine)
    init(0)
    assert get_available_cash() == 0
    assert len(get_pending_withdrawals()) == 0
    # Restore (simulating real→test switch: reload saved test state)
    restore_state()
    assert get_available_cash() == saved_available
    assert len(get_pending_withdrawals()) == saved_pending_count
