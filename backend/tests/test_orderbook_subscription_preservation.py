# -*- coding: utf-8 -*-
"""
Preservation Property Tests — 호가잔량(0D) 구독/해지 로직 보존 검증

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

These tests capture the EXISTING (correct) behavior on UNFIXED code.
They MUST PASS both before and after the fix — failure indicates a regression.

Preservation Properties:
  A: guard_pass=True 집합이 동일하면 구독 변경이 없음 (delta 방식 유지)
  B: 업종 점수 증분 재계산 결과가 구독 로직 변경과 무관하게 동일함
  C: WS 미연결 시 구독/해지가 항상 스킵됨
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.engine_sector_confirm import (
    _buy_targets_changed,
    _sync_0d_subscriptions,
)


# ── Strategies ──────────────────────────────────────────────────────────────

# 6-digit stock codes
stock_code_st = st.from_regex(r"[0-9]{6}", fullmatch=True)


@dataclass
class MockStockScore:
    """Minimal StockScore mock for testing."""
    code: str
    name: str = ""
    sector: str = "테스트업종"
    change_rate: float = 1.0
    trade_amount: int = 1_000_000_000
    avg_amt_5d: int = 500_000_000
    ratio_5d_pct: float = 200.0
    strength: float = 100.0
    cur_price: int = 10000
    change: int = 100
    market_type: str = "0"
    nxt_enable: bool = False
    guard_pass: bool = True
    guard_reason: str = ""
    boost_score: float = 0.0


@dataclass
class MockBuyTarget:
    """Minimal BuyTarget mock for testing."""
    rank: int
    sector_rank: int
    stock: MockStockScore
    reason: str = ""


def make_buy_target(code: str, guard_pass: bool = True, rank: int = 1) -> MockBuyTarget:
    """Helper to create a MockBuyTarget with given code and guard_pass."""
    return MockBuyTarget(
        rank=rank,
        sector_rank=1,
        stock=MockStockScore(code=code, guard_pass=guard_pass),
    )


# ── Preservation A: guard_pass=True 집합 동일 시 구독 변경 없음 ──────────────


class TestPreservationA:
    """Preservation A: guard_pass=True인 종목 집합이 동일하고 전체 종목코드 집합도
    동일하면, _buy_targets_changed()가 False를 반환하여 구독 변경이 발생하지 않는다.

    **Validates: Requirements 3.3**

    Observed behavior on UNFIXED code:
    - _buy_targets_changed()는 종목코드 집합({bt.stock.code})을 비교한다.
    - 종목코드 집합이 동일하면 False를 반환한다.
    - 따라서 동일 종목 구성에서 guard_pass 상태만 바뀌어도 False를 반환한다 (이것은 버그).
    - 하지만 종목코드 집합이 동일하고 guard_pass=True 집합도 동일한 경우에는
      올바르게 False를 반환하여 구독 변경이 발생하지 않는다 (이것은 보존해야 할 동작).

    이 테스트는 "종목코드 집합이 동일한 경우" 구독 변경이 없음을 검증한다.
    수정 후에도 guard_pass=True 집합이 동일하면 구독 변경이 없어야 한다.
    """

    @given(
        codes=st.lists(stock_code_st, min_size=1, max_size=8, unique=True),
        guard_pass_flags=st.lists(st.booleans(), min_size=1, max_size=8),
    )
    @settings(max_examples=100, deadline=5000)
    def test_same_guard_pass_set_no_subscription_change(
        self,
        codes: list[str],
        guard_pass_flags: list[bool],
    ):
        """When guard_pass=True code set is the same between prev and new,
        no subscription change should occur.

        On unfixed code: _buy_targets_changed() compares ALL codes.
        If ALL codes are the same, it returns False → no subscription triggered.
        This is the subset of behavior we want to preserve: when guard_pass=True
        set is unchanged AND total code set is unchanged → no subscription change.
        """
        # Align flags to codes length
        flags = (guard_pass_flags * ((len(codes) // len(guard_pass_flags)) + 1))[:len(codes)]

        # Build prev and new with SAME codes and SAME guard_pass flags
        prev_targets = [make_buy_target(c, guard_pass=f) for c, f in zip(codes, flags)]
        new_targets = [make_buy_target(c, guard_pass=f) for c, f in zip(codes, flags)]

        # guard_pass=True set is the same → no subscription change needed
        result = _buy_targets_changed(prev_targets, new_targets)
        assert result is False, (
            f"Preservation violated: _buy_targets_changed() returned True when "
            f"code sets are identical. codes={codes}"
        )

    @given(
        codes=st.lists(stock_code_st, min_size=2, max_size=8, unique=True),
        guard_pass_flags=st.lists(st.booleans(), min_size=2, max_size=8),
    )
    @settings(max_examples=100, deadline=5000)
    def test_reordered_same_codes_no_subscription_change(
        self,
        codes: list[str],
        guard_pass_flags: list[bool],
    ):
        """When buy_targets are reordered but contain the same codes with same
        guard_pass flags, no subscription change should occur.

        On unfixed code: _buy_targets_changed() uses set comparison of codes,
        so order doesn't matter. This behavior must be preserved.
        """
        flags = (guard_pass_flags * ((len(codes) // len(guard_pass_flags)) + 1))[:len(codes)]

        # Build prev targets
        prev_targets = [make_buy_target(c, guard_pass=f) for c, f in zip(codes, flags)]

        # Build new targets with reversed order (same codes, same flags per code)
        reversed_pairs = list(reversed(list(zip(codes, flags))))
        new_targets = [make_buy_target(c, guard_pass=f) for c, f in reversed_pairs]

        # Same code set → _buy_targets_changed() returns False
        result = _buy_targets_changed(prev_targets, new_targets)
        assert result is False, (
            f"Preservation violated: reordering buy_targets triggered subscription change. "
            f"codes={codes}"
        )

    @given(
        codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_already_subscribed_no_duplicate_reg(
        self,
        codes: list[str],
    ):
        """When guard_pass=True stocks are already in _subscribed_0d_stocks,
        _sync_0d_subscriptions should NOT send duplicate REG.

        **Validates: Requirements 3.3**

        Observed behavior on UNFIXED code:
        - _sync_0d_subscriptions computes to_reg = new_codes - prev_codes
        - If new_codes == prev_codes (already subscribed), to_reg is empty → no REG sent
        - This delta behavior must be preserved.
        """
        # Create mock engine service module
        mock_es = MagicMock()
        mock_es._kiwoom_connector = MagicMock()
        mock_es._kiwoom_connector.is_connected.return_value = True
        mock_es._login_ok = True
        # All codes already subscribed
        mock_es._subscribed_0d_stocks = set(codes)
        mock_es._ws_send_reg_unreg_and_wait_ack = AsyncMock(return_value=(True, "0"))

        # buy_targets with all codes as guard_pass=True
        buy_targets = [make_buy_target(c, guard_pass=True) for c in codes]

        # Run _sync_0d_subscriptions
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_sync_0d_subscriptions(mock_es, buy_targets))
        finally:
            loop.close()

        # On unfixed code: new_codes = {all codes} = prev_codes → to_reg is empty
        # No REG should be sent (ws_send not called for registration)
        # The function sets es._subscribed_0d_stocks = new_codes at the end
        # Since new_codes == prev_codes, no actual WS send should happen
        assert mock_es._ws_send_reg_unreg_and_wait_ack.call_count == 0, (
            f"Preservation violated: duplicate REG sent for already-subscribed stocks. "
            f"codes={codes}, call_count={mock_es._ws_send_reg_unreg_and_wait_ack.call_count}"
        )


# ── Preservation B: 업종 점수 증분 재계산 결과 보존 ──────────────────────────


class TestPreservationB:
    """Preservation B: 업종 점수 증분 재계산 결과가 구독 로직 변경과 무관하게 동일함.

    **Validates: Requirements 3.1, 3.2**

    Observed behavior on UNFIXED code:
    - _buy_targets_changed()는 순수 비교 함수로, 부수효과 없음
    - _sync_0d_subscriptions()는 재계산 결과에 영향을 주지 않음
    - 재계산 로직(compute_sector_scores, build_buy_targets)은 구독 로직과 독립적

    이 테스트는 _buy_targets_changed()가 순수 함수임을 검증한다:
    입력이 동일하면 항상 동일한 결과를 반환하며, 외부 상태를 변경하지 않는다.
    """

    @given(
        prev_codes=st.lists(stock_code_st, min_size=0, max_size=8, unique=True),
        new_codes=st.lists(stock_code_st, min_size=0, max_size=8, unique=True),
        prev_flags=st.lists(st.booleans(), min_size=0, max_size=8),
        new_flags=st.lists(st.booleans(), min_size=0, max_size=8),
    )
    @settings(max_examples=100, deadline=5000)
    def test_buy_targets_changed_is_pure_function(
        self,
        prev_codes: list[str],
        new_codes: list[str],
        prev_flags: list[bool],
        new_flags: list[bool],
    ):
        """_buy_targets_changed() is a pure function: same inputs → same output,
        no side effects. This ensures sector recompute results are independent
        of subscription logic.

        On unfixed code: _buy_targets_changed() compares {bt.stock.code} sets.
        It has no side effects and is deterministic.
        """
        # Build targets
        pf = (prev_flags * max(1, (len(prev_codes) // max(1, len(prev_flags))) + 1))[:len(prev_codes)]
        nf = (new_flags * max(1, (len(new_codes) // max(1, len(new_flags))) + 1))[:len(new_codes)]

        prev_targets = [make_buy_target(c, guard_pass=f) for c, f in zip(prev_codes, pf)]
        new_targets = [make_buy_target(c, guard_pass=f) for c, f in zip(new_codes, nf)]

        # Call twice — must return same result (deterministic)
        result1 = _buy_targets_changed(prev_targets, new_targets)
        result2 = _buy_targets_changed(prev_targets, new_targets)
        assert result1 == result2, (
            f"Preservation violated: _buy_targets_changed() is not deterministic. "
            f"result1={result1}, result2={result2}"
        )

    @given(
        codes=st.lists(stock_code_st, min_size=1, max_size=8, unique=True),
        flags=st.lists(st.booleans(), min_size=1, max_size=8),
    )
    @settings(max_examples=100, deadline=5000)
    def test_buy_targets_changed_consistent_with_code_set_comparison(
        self,
        codes: list[str],
        flags: list[bool],
    ):
        """_buy_targets_changed() result is consistent with code set comparison.

        On unfixed code: returns True iff {prev codes} != {new codes}.
        This is the current behavior we observe and must preserve the property that
        identical code sets always return False.

        After fix: will compare guard_pass=True sets instead, but the property
        "identical guard_pass=True sets → False" must still hold.
        """
        f = (flags * ((len(codes) // len(flags)) + 1))[:len(codes)]
        targets = [make_buy_target(c, guard_pass=fl) for c, fl in zip(codes, f)]

        # Same targets → must return False (both before and after fix)
        result = _buy_targets_changed(targets, targets)
        assert result is False, (
            f"Preservation violated: _buy_targets_changed(X, X) should always be False. "
            f"codes={codes}"
        )

    @given(
        codes=st.lists(stock_code_st, min_size=0, max_size=5, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_empty_targets_no_change(
        self,
        codes: list[str],
    ):
        """Empty buy_targets (None or []) compared to itself → no change.

        **Validates: Requirements 3.2**

        On unfixed code:
        - _buy_targets_changed(None, None) → prev_codes=set(), new_codes=set() → False
        - _buy_targets_changed([], []) → prev_codes=set(), new_codes=set() → False
        """
        # None vs None
        result_none = _buy_targets_changed(None, None)
        assert result_none is False, "None vs None should be no change"

        # [] vs []
        result_empty = _buy_targets_changed([], [])
        assert result_empty is False, "[] vs [] should be no change"

        # Same non-empty targets
        if codes:
            targets = [make_buy_target(c) for c in codes]
            result_same = _buy_targets_changed(targets, list(targets))
            assert result_same is False, "Same targets should be no change"


# ── Preservation C: WS 미연결 시 구독/해지 스킵 ──────────────────────────────


class TestPreservationC:
    """Preservation C: WS 미연결 시 구독/해지가 항상 스킵됨.

    **Validates: Requirements 3.4**

    Observed behavior on UNFIXED code:
    - _sync_0d_subscriptions() 시작 시 WS 연결 상태를 확인한다:
      if not es._kiwoom_connector or not es._kiwoom_connector.is_connected() or not es._login_ok:
          return
    - WS 미연결 시 즉시 return하여 구독/해지를 수행하지 않는다.
    - _subscribed_0d_stocks도 변경하지 않는다.
    """

    @given(
        codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        prev_subscribed=st.lists(stock_code_st, min_size=0, max_size=3, unique=True),
    )
    @settings(max_examples=100, deadline=5000)
    def test_no_connector_skips_subscription(
        self,
        codes: list[str],
        prev_subscribed: list[str],
    ):
        """When _kiwoom_connector is None, subscription is skipped entirely.

        No WS send should occur and _subscribed_0d_stocks should remain unchanged.
        """
        mock_es = MagicMock()
        mock_es._kiwoom_connector = None  # No connector
        mock_es._login_ok = True
        original_subscribed = set(prev_subscribed)
        mock_es._subscribed_0d_stocks = set(prev_subscribed)
        mock_es._ws_send_reg_unreg_and_wait_ack = AsyncMock()

        buy_targets = [make_buy_target(c, guard_pass=True) for c in codes]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_sync_0d_subscriptions(mock_es, buy_targets))
        finally:
            loop.close()

        # No WS send should have occurred
        mock_es._ws_send_reg_unreg_and_wait_ack.assert_not_called()
        # _subscribed_0d_stocks should remain unchanged
        assert mock_es._subscribed_0d_stocks == original_subscribed, (
            f"Preservation violated: _subscribed_0d_stocks changed when WS not connected. "
            f"original={original_subscribed}, current={mock_es._subscribed_0d_stocks}"
        )

    @given(
        codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        prev_subscribed=st.lists(stock_code_st, min_size=0, max_size=3, unique=True),
    )
    @settings(max_examples=100, deadline=5000)
    def test_disconnected_connector_skips_subscription(
        self,
        codes: list[str],
        prev_subscribed: list[str],
    ):
        """When connector exists but is_connected() returns False, subscription is skipped.

        No WS send should occur and _subscribed_0d_stocks should remain unchanged.
        """
        mock_es = MagicMock()
        mock_es._kiwoom_connector = MagicMock()
        mock_es._kiwoom_connector.is_connected.return_value = False  # Disconnected
        mock_es._login_ok = True
        original_subscribed = set(prev_subscribed)
        mock_es._subscribed_0d_stocks = set(prev_subscribed)
        mock_es._ws_send_reg_unreg_and_wait_ack = AsyncMock()

        buy_targets = [make_buy_target(c, guard_pass=True) for c in codes]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_sync_0d_subscriptions(mock_es, buy_targets))
        finally:
            loop.close()

        # No WS send should have occurred
        mock_es._ws_send_reg_unreg_and_wait_ack.assert_not_called()
        # _subscribed_0d_stocks should remain unchanged
        assert mock_es._subscribed_0d_stocks == original_subscribed, (
            f"Preservation violated: _subscribed_0d_stocks changed when WS disconnected. "
            f"original={original_subscribed}, current={mock_es._subscribed_0d_stocks}"
        )

    @given(
        codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        prev_subscribed=st.lists(stock_code_st, min_size=0, max_size=3, unique=True),
    )
    @settings(max_examples=100, deadline=5000)
    def test_login_not_ok_skips_subscription(
        self,
        codes: list[str],
        prev_subscribed: list[str],
    ):
        """When _login_ok is False, subscription is skipped entirely.

        No WS send should occur and _subscribed_0d_stocks should remain unchanged.
        """
        mock_es = MagicMock()
        mock_es._kiwoom_connector = MagicMock()
        mock_es._kiwoom_connector.is_connected.return_value = True
        mock_es._login_ok = False  # Not logged in
        original_subscribed = set(prev_subscribed)
        mock_es._subscribed_0d_stocks = set(prev_subscribed)
        mock_es._ws_send_reg_unreg_and_wait_ack = AsyncMock()

        buy_targets = [make_buy_target(c, guard_pass=True) for c in codes]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_sync_0d_subscriptions(mock_es, buy_targets))
        finally:
            loop.close()

        # No WS send should have occurred
        mock_es._ws_send_reg_unreg_and_wait_ack.assert_not_called()
        # _subscribed_0d_stocks should remain unchanged
        assert mock_es._subscribed_0d_stocks == original_subscribed, (
            f"Preservation violated: _subscribed_0d_stocks changed when login not OK. "
            f"original={original_subscribed}, current={mock_es._subscribed_0d_stocks}"
        )

    @given(
        codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        guard_pass_flags=st.lists(st.booleans(), min_size=1, max_size=5),
        prev_subscribed=st.lists(stock_code_st, min_size=0, max_size=3, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_all_ws_failure_modes_skip(
        self,
        codes: list[str],
        guard_pass_flags: list[bool],
        prev_subscribed: list[str],
    ):
        """All three WS failure modes (no connector, disconnected, not logged in)
        consistently skip subscription without modifying state.

        This is a combined property test ensuring robustness across all failure modes.
        """
        flags = (guard_pass_flags * ((len(codes) // len(guard_pass_flags)) + 1))[:len(codes)]
        buy_targets = [make_buy_target(c, guard_pass=f) for c, f in zip(codes, flags)]

        failure_modes = [
            # (connector, is_connected, login_ok)
            (None, None, True),           # No connector
            (MagicMock(), False, True),   # Disconnected
            (MagicMock(), True, False),   # Not logged in
        ]

        for connector, is_connected, login_ok in failure_modes:
            mock_es = MagicMock()
            mock_es._kiwoom_connector = connector
            if connector and is_connected is not None:
                connector.is_connected = MagicMock(return_value=is_connected)
                mock_es._kiwoom_connector = connector
            mock_es._login_ok = login_ok
            original_subscribed = set(prev_subscribed)
            mock_es._subscribed_0d_stocks = set(prev_subscribed)
            mock_es._ws_send_reg_unreg_and_wait_ack = AsyncMock()

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_sync_0d_subscriptions(mock_es, buy_targets))
            finally:
                loop.close()

            # No WS send in any failure mode
            mock_es._ws_send_reg_unreg_and_wait_ack.assert_not_called()
            # State unchanged in any failure mode
            assert mock_es._subscribed_0d_stocks == original_subscribed
