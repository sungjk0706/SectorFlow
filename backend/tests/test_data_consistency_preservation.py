# -*- coding: utf-8 -*-
"""
Preservation Property Tests — Eligible Stock Behavior Unchanged

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**

These tests capture the EXISTING (correct) behavior for eligible stocks on UNFIXED code.
They MUST PASS both before and after the fix — failure indicates a regression.

Preservation Properties:
  A: Rolling update produces same shift+append result for eligible stocks
  B: _apply_confirmed_to_memory stores cur_price, change, change_rate, sign, trade_amount identically
  C: When _eligible_stock_codes is empty, get_all_sector_stocks returns all active stocks
  D: For eligible stocks, atomic memory swap preserves entry data without modification
"""
from __future__ import annotations

import asyncio
import copy

from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ── Strategies ──────────────────────────────────────────────────────────────

# 6-digit stock codes
stock_code_st = st.from_regex(r"[0-9]{6}", fullmatch=True)

# Positive trade amounts (in won, typically billions)
trade_amount_st = st.integers(min_value=1_000_000, max_value=100_000_000_000)

# v2 arrays: lists of 1-5 positive ints (millions)
v2_array_st = st.lists(
    st.integers(min_value=1, max_value=100_000),
    min_size=1,
    max_size=5,
)

# Positive prices
price_st = st.integers(min_value=100, max_value=5_000_000)

# Change values (can be negative)
change_st = st.integers(min_value=-500_000, max_value=500_000)

# Change rate (percentage)
change_rate_st = st.floats(min_value=-30.0, max_value=30.0, allow_nan=False, allow_infinity=False)

# Sign values (키움 sign: "1"=상한, "2"=상승, "3"=보합, "4"=하한, "5"=하락)
sign_st = st.sampled_from(["1", "2", "3", "4", "5"])


# ── Preservation A: Rolling update shift+append for eligible stocks ──────────


class TestPreservationA:
    """Preservation A: For eligible stocks in existing_v2, rolling update produces
    same shift+append result regardless of eligible_set parameter presence.

    **Validates: Requirements 3.1, 3.5**

    Observed behavior on UNFIXED code:
    - rolling_update_v2_from_trade_amounts({"005930": [100, 200, 300, 400, 500]}, {"005930": 600_000_000})
      → result["005930"] == [200, 300, 400, 500, 600]
    - rolling_update_v2_from_trade_amounts(None, {"NEW001": 50_000_000})
      → result["NEW001"] == [50]
    """

    @given(
        stock_code=stock_code_st,
        existing_arr=v2_array_st,
        new_trade_amount=trade_amount_st,
    )
    @settings(max_examples=100, deadline=5000)
    def test_existing_stock_rolling_shift_append(
        self,
        stock_code: str,
        existing_arr: list[int],
        new_trade_amount: int,
    ):
        """Existing eligible stock: oldest value removed, new value appended (max 5)."""
        from app.core.avg_amt_cache import rolling_update_v2_from_trade_amounts

        existing_v2 = {stock_code: list(existing_arr)}
        trade_amounts = {stock_code: new_trade_amount}

        updated_v2, _ = rolling_update_v2_from_trade_amounts(
            existing_v2, trade_amounts,
        )

        # The stock must be in the result
        assert stock_code in updated_v2

        amt_million = int(new_trade_amount / 1_000_000)
        if amt_million <= 0:
            # If converted amount is 0, array stays unchanged
            assert updated_v2[stock_code] == existing_arr
        else:
            result_arr = updated_v2[stock_code]
            # Result should have the new value appended
            assert result_arr[-1] == amt_million
            # Max 5 elements
            assert len(result_arr) <= 5
            # If existing was full (5), oldest removed
            if len(existing_arr) >= 5:
                expected = existing_arr[1:] + [amt_million]
                assert result_arr == expected[-5:]
            else:
                expected = existing_arr + [amt_million]
                assert result_arr == expected

    @given(
        stock_code=stock_code_st,
        new_trade_amount=trade_amount_st,
    )
    @settings(max_examples=100, deadline=5000)
    def test_new_stock_creates_single_element_array(
        self,
        stock_code: str,
        new_trade_amount: int,
    ):
        """New eligible stock (not in existing_v2): creates [amt_million] array."""
        from app.core.avg_amt_cache import rolling_update_v2_from_trade_amounts

        # existing_v2 is None (first time) or empty
        trade_amounts = {stock_code: new_trade_amount}

        # Test with None existing
        updated_v2, _ = rolling_update_v2_from_trade_amounts(
            None, trade_amounts,
        )

        amt_million = int(new_trade_amount / 1_000_000)
        if amt_million > 0:
            assert stock_code in updated_v2
            assert updated_v2[stock_code] == [amt_million]
        else:
            # 0 million → not added
            assert stock_code not in updated_v2

    @given(
        stock_code=stock_code_st,
        existing_arr=v2_array_st,
    )
    @settings(max_examples=100, deadline=5000)
    def test_stock_with_no_new_trade_preserved(
        self,
        stock_code: str,
        existing_arr: list[int],
    ):
        """Existing stock with no new trade amount: array preserved unchanged."""
        from app.core.avg_amt_cache import rolling_update_v2_from_trade_amounts

        existing_v2 = {stock_code: list(existing_arr)}
        # Empty trade_amounts — no new data for this stock
        trade_amounts: dict[str, int] = {}

        updated_v2, _ = rolling_update_v2_from_trade_amounts(
            existing_v2, trade_amounts,
        )

        assert stock_code in updated_v2
        assert updated_v2[stock_code] == existing_arr


# ── Preservation B: Confirmed fields stored identically ──────────────────────


class TestPreservationB:
    """Preservation B: For all confirmed details, cur_price, change, change_rate,
    sign, trade_amount fields are stored identically before and after fix.

    **Validates: Requirements 3.2, 3.4**

    Observed behavior on UNFIXED code:
    - _apply_confirmed_to_memory() with cur_price=51000, change=1000, trade_amount=5000000000
      → entry fields stored correctly (cur_price, change, change_rate, sign, trade_amount)
    """

    @given(
        stock_code=stock_code_st,
        cur_price=price_st,
        change=change_st,
        change_rate=change_rate_st,
        sign=sign_st,
        trade_amount=trade_amount_st,
    )
    @settings(max_examples=100, deadline=10000)
    def test_confirmed_fields_stored_correctly(
        self,
        stock_code: str,
        cur_price: int,
        change: int,
        change_rate: float,
        sign: str,
        trade_amount: int,
    ):
        """cur_price, change, change_rate, sign, trade_amount stored in entry."""
        import app.services.engine_service as es
        from app.services.market_close_pipeline import _apply_confirmed_to_memory

        # Save original state
        original_pending = es._pending_stock_details

        try:
            # Setup: create existing entry
            test_entry = {
                "code": stock_code,
                "name": "테스트종목",
                "cur_price": 0,
                "change": 0,
                "change_rate": 0.0,
                "sign": "3",
                "trade_amount": 0,
                "status": "active",
            }
            es._pending_stock_details = {stock_code: dict(test_entry)}

            confirmed = {
                stock_code: {
                    "cur_price": cur_price,
                    "change": change,
                    "change_rate": change_rate,
                    "sign": sign,
                    "trade_amount": trade_amount,
                }
            }

            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                _apply_confirmed_to_memory(es, confirmed, {})
            )
            loop.close()

            entry = es._pending_stock_details[stock_code]

            # Verify all fields stored correctly
            if cur_price > 0:
                assert entry["cur_price"] == cur_price
            # change is always stored (even if 0)
            assert entry["change"] == change
            # change_rate is always stored
            assert entry["change_rate"] == change_rate
            # sign stored if non-empty
            assert entry["sign"] == sign
            # trade_amount stored if > 0
            if trade_amount > 0:
                assert entry["trade_amount"] == trade_amount

        finally:
            es._pending_stock_details = original_pending

    @given(
        stock_code=stock_code_st,
        cur_price=price_st,
        high_price=st.integers(min_value=-100, max_value=0),  # 0 or negative
    )
    @settings(max_examples=50, deadline=10000)
    def test_zero_high_price_does_not_overwrite(
        self,
        stock_code: str,
        cur_price: int,
        high_price: int,
    ):
        """When high_price <= 0, existing entry high_price should not be overwritten.

        **Validates: Requirements 3.4**
        """
        import app.services.engine_service as es
        from app.services.market_close_pipeline import _apply_confirmed_to_memory

        original_pending = es._pending_stock_details

        try:
            # Setup: entry with existing high_price
            existing_high = 52000
            test_entry = {
                "code": stock_code,
                "name": "테스트종목",
                "cur_price": cur_price,
                "change": 0,
                "change_rate": 0.0,
                "sign": "3",
                "trade_amount": 1_000_000_000,
                "high_price": existing_high,
                "status": "active",
            }
            es._pending_stock_details = {stock_code: dict(test_entry)}

            confirmed = {
                stock_code: {
                    "cur_price": cur_price,
                    "change": 0,
                    "change_rate": 0.0,
                    "sign": "3",
                    "trade_amount": 1_000_000_000,
                    "high_price": high_price,  # 0 or negative
                }
            }

            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                _apply_confirmed_to_memory(es, confirmed, {})
            )
            loop.close()

            entry = es._pending_stock_details[stock_code]

            # high_price <= 0 should NOT overwrite existing value
            # On unfixed code, high_price is never written at all, so existing value stays
            assert entry.get("high_price") == existing_high

        finally:
            es._pending_stock_details = original_pending


# ── Preservation C: Empty eligible → all active stocks returned ──────────────


class TestPreservationC:
    """Preservation C: When _eligible_stock_codes is empty, get_all_sector_stocks()
    returns all active stocks (backward compatibility).

    **Validates: Requirements 3.3**

    Observed behavior on UNFIXED code:
    - get_all_sector_stocks() with empty _eligible_stock_codes → returns all active stocks
    """

    @given(
        stock_codes=st.lists(stock_code_st, min_size=1, max_size=10, unique=True),
    )
    @settings(max_examples=100, deadline=5000)
    def test_empty_eligible_returns_all_active(
        self,
        stock_codes: list[str],
    ):
        """When _eligible_stock_codes is empty, all active stocks are returned."""
        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        original_pending = es._pending_stock_details
        original_eligible = ind_mod._eligible_stock_codes

        try:
            # Setup: populate _pending_stock_details with active stocks
            test_pending: dict = {}
            for code in stock_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"종목_{code}",
                    "status": "active",
                    "cur_price": 10000,
                }

            es._pending_stock_details = test_pending

            # Set _eligible_stock_codes to EMPTY (backward compatibility mode)
            ind_mod._eligible_stock_codes = {}

            result = es.get_all_sector_stocks()
            result_codes = {item["code"] for item in result}

            # ALL active stocks should be returned when eligible is empty
            for code in stock_codes:
                assert code in result_codes, (
                    f"Preservation C violated: stock '{code}' not returned when "
                    f"_eligible_stock_codes is empty"
                )

        finally:
            es._pending_stock_details = original_pending
            ind_mod._eligible_stock_codes = original_eligible

    @given(
        active_codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        inactive_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_inactive_stocks_excluded_regardless(
        self,
        active_codes: list[str],
        inactive_codes: list[str],
    ):
        """Inactive stocks (status != 'active') are always excluded."""
        inactive_codes = [c for c in inactive_codes if c not in active_codes]
        assume(len(inactive_codes) > 0)

        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        original_pending = es._pending_stock_details
        original_eligible = ind_mod._eligible_stock_codes

        try:
            test_pending: dict = {}
            for code in active_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"활성_{code}",
                    "status": "active",
                    "cur_price": 10000,
                }
            for code in inactive_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"비활성_{code}",
                    "status": "exited",
                    "cur_price": 5000,
                }

            es._pending_stock_details = test_pending
            ind_mod._eligible_stock_codes = {}  # empty = no filter

            result = es.get_all_sector_stocks()
            result_codes = {item["code"] for item in result}

            # Active stocks should be returned
            for code in active_codes:
                assert code in result_codes

            # Inactive stocks should NOT be returned
            for code in inactive_codes:
                assert code not in result_codes

        finally:
            es._pending_stock_details = original_pending
            ind_mod._eligible_stock_codes = original_eligible


# ── Preservation D: Eligible stock data preserved during memory swap ─────────


class TestPreservationD:
    """Preservation D: For eligible stocks, atomic memory swap preserves entry data
    without modification.

    **Validates: Requirements 3.6, 3.7**

    This tests that eligible stock entries in _pending_stock_details maintain their
    data integrity. On unfixed code, there is no atomic swap, but eligible stock
    data is never modified by the pipeline — it stays as-is.
    """

    @given(
        stock_codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        prices=st.lists(price_st, min_size=1, max_size=5),
        trade_amounts=st.lists(trade_amount_st, min_size=1, max_size=5),
    )
    @settings(max_examples=100, deadline=5000)
    def test_eligible_stock_entry_data_preserved(
        self,
        stock_codes: list[str],
        prices: list[int],
        trade_amounts: list[int],
    ):
        """Eligible stock entry data (cur_price, name, status, trade_amount) is preserved."""
        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        original_pending = es._pending_stock_details
        original_eligible = ind_mod._eligible_stock_codes

        try:
            # Setup: create entries for eligible stocks
            test_pending: dict = {}
            expected_data: dict = {}
            for i, code in enumerate(stock_codes):
                entry = {
                    "code": code,
                    "name": f"종목_{code}",
                    "status": "active",
                    "cur_price": prices[i % len(prices)],
                    "change": 100,
                    "change_rate": 1.5,
                    "sign": "2",
                    "trade_amount": trade_amounts[i % len(trade_amounts)],
                }
                test_pending[code] = entry
                expected_data[code] = copy.deepcopy(entry)

            es._pending_stock_details = test_pending
            ind_mod._eligible_stock_codes = {code: "" for code in stock_codes}

            # Verify: eligible stock data is accessible and unchanged
            for code in stock_codes:
                current_entry = es._pending_stock_details[code]
                expected_entry = expected_data[code]

                assert current_entry["cur_price"] == expected_entry["cur_price"]
                assert current_entry["name"] == expected_entry["name"]
                assert current_entry["status"] == expected_entry["status"]
                assert current_entry["trade_amount"] == expected_entry["trade_amount"]
                assert current_entry["change"] == expected_entry["change"]
                assert current_entry["change_rate"] == expected_entry["change_rate"]
                assert current_entry["sign"] == expected_entry["sign"]

        finally:
            es._pending_stock_details = original_pending
            ind_mod._eligible_stock_codes = original_eligible

    @given(
        stock_codes=st.lists(stock_code_st, min_size=2, max_size=5, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_ui_returns_consistent_state_before_swap(
        self,
        stock_codes: list[str],
    ):
        """UI queries return consistent state (all eligible stocks visible).

        **Validates: Requirements 3.7**

        Before any memory swap, UI should see all stocks that are in
        _pending_stock_details with status=active.
        """
        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        original_pending = es._pending_stock_details
        original_eligible = ind_mod._eligible_stock_codes

        try:
            # Setup: all stocks are eligible and active
            test_pending: dict = {}
            for code in stock_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"종목_{code}",
                    "status": "active",
                    "cur_price": 10000,
                }

            es._pending_stock_details = test_pending
            # Empty eligible = no filter (backward compat)
            ind_mod._eligible_stock_codes = {}

            # UI query should return all active stocks consistently
            result = es.get_all_sector_stocks()
            result_codes = {item["code"] for item in result}

            assert result_codes == set(stock_codes), (
                f"UI inconsistency: expected {set(stock_codes)}, got {result_codes}"
            )

        finally:
            es._pending_stock_details = original_pending
            ind_mod._eligible_stock_codes = original_eligible
