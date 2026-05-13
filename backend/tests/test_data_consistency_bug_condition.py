# -*- coding: utf-8 -*-
"""
Bug Condition Exploration Test — Data Consistency Violations (Ineligible Stock Retention)

**Validates: Requirements 1.1, 1.2, 1.3, 1.4**

This test encodes the EXPECTED (correct) behavior. On UNFIXED code, these tests
MUST FAIL — failure confirms the bugs exist. After the fix is implemented,
these tests should PASS.

4 Independent Bugs:
  Bug 1 (Cache Stale): rolling_update_v2_from_trade_amounts retains ineligible stocks
  Bug 2 (High Price): _apply_confirmed_to_memory does not store high_price
  Bug 3 (UI Filter): get_all_sector_stocks returns ineligible active stocks
  Bug 4 (Memory Reload): _pending_stock_details retains ineligible stocks after saves
"""
from __future__ import annotations

import asyncio

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

# Positive high prices
high_price_st = st.integers(min_value=100, max_value=5_000_000)


# ── Bug 1: Cache Stale — Ineligible stock retention in rolling_update_v2 ────


class TestBug1CacheStale:
    """Bug 1: rolling_update_v2_from_trade_amounts retains ineligible stocks in result.

    **Validates: Requirements 1.1**

    The function currently has no eligible_set parameter, so it cannot filter
    ineligible stocks from existing_v2. This test asserts the EXPECTED behavior:
    ineligible stocks should NOT appear in the result.
    """

    @given(
        eligible_codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        ineligible_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
        trade_amounts_values=st.lists(trade_amount_st, min_size=1, max_size=5),
    )
    @settings(max_examples=50, deadline=5000)
    def test_ineligible_stocks_not_in_updated_v2(
        self,
        eligible_codes: list[str],
        ineligible_codes: list[str],
        trade_amounts_values: list[int],
    ):
        """Ineligible stocks in existing_v2 should NOT appear in result updated_v2."""
        # Ensure no overlap between eligible and ineligible
        ineligible_codes = [c for c in ineligible_codes if c not in eligible_codes]
        assume(len(ineligible_codes) > 0)

        from app.core.avg_amt_cache import rolling_update_v2_from_trade_amounts

        # Build existing_v2 with both eligible and ineligible stocks
        existing_v2: dict[str, list[int]] = {}
        for code in eligible_codes:
            existing_v2[code] = [100, 200, 300, 400, 500]
        for code in ineligible_codes:
            existing_v2[code] = [50, 60, 70, 80, 90]

        # Build trade_amounts for eligible stocks only
        trade_amounts: dict[str, int] = {}
        for i, code in enumerate(eligible_codes):
            trade_amounts[code] = trade_amounts_values[i % len(trade_amounts_values)]

        eligible_set = set(eligible_codes)

        # Call the function — on unfixed code, eligible_set param doesn't exist
        # so we call without it (the bug: no filtering happens)
        try:
            updated_v2, updated_high_arr = rolling_update_v2_from_trade_amounts(
                existing_v2, trade_amounts,
                eligible_set=eligible_set,
            )
        except TypeError:
            # If eligible_set param doesn't exist yet, call without it
            # and assert the bug condition: ineligible stocks ARE retained
            updated_v2, updated_high_arr = rolling_update_v2_from_trade_amounts(
                existing_v2, trade_amounts,
            )

        # EXPECTED BEHAVIOR: ineligible stocks should NOT be in result
        for code in ineligible_codes:
            assert code not in updated_v2, (
                f"Bug 1 confirmed: ineligible stock '{code}' retained in updated_v2"
            )

    @given(
        eligible_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
        ineligible_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
        high_prices_values=st.lists(high_price_st, min_size=1, max_size=3),
    )
    @settings(max_examples=50, deadline=5000)
    def test_ineligible_stocks_not_in_updated_high_arr(
        self,
        eligible_codes: list[str],
        ineligible_codes: list[str],
        high_prices_values: list[int],
    ):
        """Ineligible stocks in existing high_5d_arr should NOT appear in result."""
        ineligible_codes = [c for c in ineligible_codes if c not in eligible_codes]
        assume(len(ineligible_codes) > 0)

        from app.core.avg_amt_cache import rolling_update_v2_from_trade_amounts

        # Build existing data with both eligible and ineligible
        existing_v2: dict[str, list[int]] = {}
        existing_high_arr: dict[str, list[int]] = {}
        for code in eligible_codes:
            existing_v2[code] = [100, 200, 300]
            existing_high_arr[code] = [10000, 11000, 12000]
        for code in ineligible_codes:
            existing_v2[code] = [50, 60, 70]
            existing_high_arr[code] = [5000, 6000, 7000]

        # Trade amounts and high prices for eligible only
        trade_amounts: dict[str, int] = {}
        high_prices: dict[str, int] = {}
        for i, code in enumerate(eligible_codes):
            trade_amounts[code] = 5_000_000_000
            high_prices[code] = high_prices_values[i % len(high_prices_values)]

        eligible_set = set(eligible_codes)

        try:
            updated_v2, updated_high_arr = rolling_update_v2_from_trade_amounts(
                existing_v2, trade_amounts,
                high_prices=high_prices,
                high_5d_arr=existing_high_arr,
                eligible_set=eligible_set,
            )
        except TypeError:
            updated_v2, updated_high_arr = rolling_update_v2_from_trade_amounts(
                existing_v2, trade_amounts,
                high_prices=high_prices,
                high_5d_arr=existing_high_arr,
            )

        # EXPECTED BEHAVIOR: ineligible stocks should NOT be in high arr result
        for code in ineligible_codes:
            assert code not in updated_high_arr, (
                f"Bug 1 confirmed: ineligible stock '{code}' retained in updated_high_arr"
            )


# ── Bug 2: High Price — _apply_confirmed_to_memory does not store high_price ─


class TestBug2HighPrice:
    """Bug 2: _apply_confirmed_to_memory does not store high_price field.

    **Validates: Requirements 1.2**

    When ka10086 response contains high_price > 0, the function should store it
    in the entry. Currently it only stores cur_price, change, change_rate, sign,
    trade_amount — high_price is missing.
    """

    @given(
        stock_code=stock_code_st,
        high_price=st.integers(min_value=100, max_value=5_000_000),
        cur_price=st.integers(min_value=100, max_value=5_000_000),
    )
    @settings(max_examples=50, deadline=10000)
    def test_high_price_stored_in_entry(
        self,
        stock_code: str,
        high_price: int,
        cur_price: int,
    ):
        """high_price > 0 in confirmed detail should be stored in entry."""
        import app.services.engine_service as es
        from app.services.market_close_pipeline import _apply_confirmed_to_memory

        # Setup: create an existing entry in _pending_stock_details
        original_pending = es._pending_stock_details
        test_entry = {
            "code": stock_code,
            "name": "테스트종목",
            "cur_price": cur_price - 100,
            "change": 0,
            "change_rate": 0.0,
            "sign": "2",
            "trade_amount": 1_000_000_000,
            "status": "active",
        }
        es._pending_stock_details = {stock_code: test_entry}

        confirmed = {
            stock_code: {
                "cur_price": cur_price,
                "change": 100,
                "change_rate": 1.5,
                "sign": "2",
                "trade_amount": 5_000_000_000,
                "high_price": high_price,
            }
        }

        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                _apply_confirmed_to_memory(es, confirmed, {})
            )
            loop.close()

            entry = es._pending_stock_details[stock_code]
            # EXPECTED BEHAVIOR: high_price should be stored
            assert entry.get("high_price") == high_price, (
                f"Bug 2 confirmed: high_price={high_price} not stored in entry. "
                f"Entry keys: {list(entry.keys())}"
            )
        finally:
            es._pending_stock_details = original_pending


# ── Bug 3: UI Filter — get_all_sector_stocks returns ineligible active stocks ─


class TestBug3UIFilter:
    """Bug 3: get_all_sector_stocks returns ineligible active stocks.

    **Validates: Requirements 1.3**

    When _eligible_stock_codes is non-empty, get_all_sector_stocks should only
    return stocks that are in the eligible set. Currently it returns ALL active
    stocks regardless of eligibility.
    """

    @given(
        eligible_codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        ineligible_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_ineligible_stocks_not_in_ui_result(
        self,
        eligible_codes: list[str],
        ineligible_codes: list[str],
    ):
        """Ineligible active stocks should NOT appear in get_all_sector_stocks result."""
        ineligible_codes = [c for c in ineligible_codes if c not in eligible_codes]
        assume(len(ineligible_codes) > 0)

        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        # Save originals
        original_pending = es._pending_stock_details
        original_eligible = ind_mod._eligible_stock_codes

        try:
            # Setup: populate _pending_stock_details with both eligible and ineligible
            test_pending: dict = {}
            for code in eligible_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"적격_{code}",
                    "status": "active",
                    "cur_price": 10000,
                }
            for code in ineligible_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"부적격_{code}",
                    "status": "active",
                    "cur_price": 5000,
                }

            es._pending_stock_details = test_pending

            # Set eligible_stock_codes to only eligible codes
            ind_mod._eligible_stock_codes = {code: "" for code in eligible_codes}

            # Call get_all_sector_stocks
            result = es.get_all_sector_stocks()
            result_codes = {item["code"] for item in result}

            # EXPECTED BEHAVIOR: ineligible stocks should NOT be in result
            for code in ineligible_codes:
                assert code not in result_codes, (
                    f"Bug 3 confirmed: ineligible stock '{code}' appears in "
                    f"get_all_sector_stocks() result (eligible={len(eligible_codes)}, "
                    f"returned={len(result_codes)})"
                )
        finally:
            es._pending_stock_details = original_pending
            ind_mod._eligible_stock_codes = original_eligible


# ── Bug 4: Memory Reload — _pending_stock_details retains ineligible stocks ───


class TestBug4MemoryReload:
    """Bug 4: After all saves completed, _pending_stock_details retains ineligible stocks.

    **Validates: Requirements 1.4**

    After the pipeline completes (확정시세 + 5일거래대금/고가 + 업종매핑 저장),
    _pending_stock_details should only contain eligible stocks. Currently there is
    no atomic memory swap, so ineligible stocks remain.
    """

    @given(
        eligible_codes=st.lists(stock_code_st, min_size=2, max_size=5, unique=True),
        ineligible_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_ineligible_stocks_removed_after_saves_completed(
        self,
        eligible_codes: list[str],
        ineligible_codes: list[str],
    ):
        """After all saves completed, _pending_stock_details should only have eligible stocks."""
        ineligible_codes = [c for c in ineligible_codes if c not in eligible_codes]
        assume(len(ineligible_codes) > 0)

        import app.services.engine_service as es
        import app.core.industry_map as ind_mod

        # Save originals
        original_pending = es._pending_stock_details
        original_eligible = ind_mod._eligible_stock_codes

        try:
            # Setup: simulate state after all saves completed
            # _pending_stock_details has both eligible and ineligible active stocks
            test_pending: dict = {}
            for code in eligible_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"적격_{code}",
                    "status": "active",
                    "cur_price": 10000,
                    "trade_amount": 5_000_000_000,
                }
            for code in ineligible_codes:
                test_pending[code] = {
                    "code": code,
                    "name": f"부적격_{code}",
                    "status": "active",
                    "cur_price": 5000,
                    "trade_amount": 1_000_000_000,
                }

            es._pending_stock_details = test_pending

            # Set eligible_stock_codes (non-empty = filter should apply)
            ind_mod._eligible_stock_codes = {code: "" for code in eligible_codes}

            # Simulate "all saves completed" state:
            # In the unfixed code, there is NO atomic memory swap after saves complete.
            # The bug is that _pending_stock_details is never filtered to eligible-only.
            # We check the current state of _pending_stock_details after "saves completed".
            # (In the fixed code, an atomic swap would remove ineligible stocks here.)

            # EXPECTED BEHAVIOR: after all saves completed, only eligible stocks remain
            active_codes_in_pending = {
                cd for cd, entry in es._pending_stock_details.items()
                if entry.get("status") == "active"
            }
            eligible_set = set(ind_mod._eligible_stock_codes.keys())

            for code in ineligible_codes:
                assert code not in active_codes_in_pending or code in eligible_set, (
                    f"Bug 4 confirmed: ineligible stock '{code}' remains active in "
                    f"_pending_stock_details after all saves completed "
                    f"(pending_active={len(active_codes_in_pending)}, "
                    f"eligible={len(eligible_set)})"
                )
        finally:
            es._pending_stock_details = original_pending
            ind_mod._eligible_stock_codes = original_eligible
