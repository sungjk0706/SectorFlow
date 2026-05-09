# -*- coding: utf-8 -*-
"""
Bug Condition Exploration Test — 호가잔량(0D) 구독/해지 로직 버그

**Validates: Requirements 1.1, 1.2, 1.3**

This test encodes the EXPECTED (correct) behavior. On UNFIXED code, these tests
MUST FAIL — failure confirms the bugs exist. After the fix is implemented,
these tests should PASS.

Bug Condition:
  `_buy_targets_changed()`가 guard_pass 상태를 무시하고 종목코드 집합만 비교하며,
  `_sync_0d_subscriptions()`가 guard_pass=False 종목까지 구독 대상에 포함한다.

Expected Behavior:
  guard_pass=True 집합이 변경된 경우에만 delta(REG/REMOVE) 발생해야 한다.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.engine_sector_confirm import _buy_targets_changed


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


# ── Test 1: buy_targets 순서만 변경 시 _buy_targets_changed() 동작 검증 ────
# 업종순위만 변동하고 guard_pass 상태는 동일한 경우, 구독 변경이 발생하면 안 됨


class TestBug1OrderChangeTriggersSubscription:
    """Bug 1: 업종순위 변동으로 buy_targets 구성이 바뀌면 guard_pass 상태 변화 없이도
    구독/해지가 트리거된다.

    **Validates: Requirements 1.1**

    Expected behavior: guard_pass=True인 종목 집합이 동일하면 구독 변경이 없어야 한다.
    Current bug: _buy_targets_changed()가 종목코드 집합만 비교하여, 업종순위 변동으로
    buy_targets 구성이 바뀌면 (다른 종목이 진입/이탈) 구독 변경을 트리거한다.
    """

    @given(
        common_codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        extra_prev_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
        extra_new_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_buy_targets_changed_ignores_guard_pass(
        self,
        common_codes: list[str],
        extra_prev_codes: list[str],
        extra_new_codes: list[str],
    ):
        """When guard_pass=True set is the same but buy_targets composition differs,
        _buy_targets_changed() should return False.

        Scenario: prev has [A,B,C] (all guard_pass=True), new has [A,B,D] (all guard_pass=True).
        The guard_pass=True set changed ({A,B,C} vs {A,B,D}), so subscription change IS needed.
        But if we keep guard_pass=True set the same and only change which stocks are in buy_targets
        by having some with guard_pass=False...

        Actually, the real bug: _buy_targets_changed() compares ALL stock codes in buy_targets,
        not just guard_pass=True codes. When buy_targets includes guard_pass=False stocks
        (which shouldn't trigger subscriptions), any composition change triggers subscription.

        For this test: prev and new have the SAME guard_pass=True codes but DIFFERENT
        total composition (extra stocks with guard_pass=False differ).
        Expected: _buy_targets_changed() should return False (guard_pass=True set unchanged)
        Actual (bug): returns True (because total code sets differ)
        """
        # Ensure no overlap between common and extras
        all_codes = set(common_codes)
        extra_prev_codes = [c for c in extra_prev_codes if c not in all_codes]
        extra_new_codes = [c for c in extra_new_codes if c not in all_codes and c not in extra_prev_codes]
        assume(len(extra_prev_codes) > 0 or len(extra_new_codes) > 0)
        assume(extra_prev_codes != extra_new_codes)

        # Build prev_targets: common codes (guard_pass=True) + extra_prev (guard_pass=False)
        prev_targets = [make_buy_target(c, guard_pass=True) for c in common_codes]
        prev_targets += [make_buy_target(c, guard_pass=False) for c in extra_prev_codes]

        # Build new_targets: common codes (guard_pass=True) + extra_new (guard_pass=False)
        new_targets = [make_buy_target(c, guard_pass=True) for c in common_codes]
        new_targets += [make_buy_target(c, guard_pass=False) for c in extra_new_codes]

        # EXPECTED BEHAVIOR: guard_pass=True set is the same → should return False
        # BUG: _buy_targets_changed() compares ALL codes, so it returns True
        result = _buy_targets_changed(prev_targets, new_targets)
        assert result is False, (
            f"Bug confirmed: _buy_targets_changed() returns True when guard_pass=True "
            f"set is unchanged. prev_codes={set(common_codes) | set(extra_prev_codes)}, "
            f"new_codes={set(common_codes) | set(extra_new_codes)}, "
            f"guard_pass=True set (same)={set(common_codes)}"
        )


# ── Test 2: guard_pass=False 종목이 구독되는 버그 검증 ────────────────────


class TestBug2GuardPassFalseSubscribed:
    """Bug 2: _sync_0d_subscriptions()가 guard_pass=False 종목까지 구독한다.

    **Validates: Requirements 1.2**

    Expected behavior: guard_pass=True인 종목만 구독 대상에 포함되어야 한다.
    Current bug: new_codes = {bt.stock.code for bt in new_buy_targets} 로
    guard_pass 여부와 무관하게 전체 buy_targets를 구독 대상으로 삼는다.
    """

    @given(
        pass_codes=st.lists(stock_code_st, min_size=1, max_size=5, unique=True),
        fail_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
    )
    @settings(max_examples=50, deadline=5000)
    def test_guard_pass_false_stocks_not_subscribed(
        self,
        pass_codes: list[str],
        fail_codes: list[str],
    ):
        """guard_pass=False stocks should NOT be included in subscription target set.

        Expected: only guard_pass=True codes are subscribed
        Bug: ALL codes in buy_targets are subscribed regardless of guard_pass
        """
        # Ensure no overlap
        fail_codes = [c for c in fail_codes if c not in pass_codes]
        assume(len(fail_codes) > 0)

        # Build buy_targets with both pass and fail stocks
        buy_targets = [make_buy_target(c, guard_pass=True) for c in pass_codes]
        buy_targets += [make_buy_target(c, guard_pass=False) for c in fail_codes]

        # Test the actual subscription target calculation logic used by _sync_0d_subscriptions
        # After fix: new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}
        # Before fix (bug): new_codes = {bt.stock.code for bt in new_buy_targets}
        from app.services.engine_sector_confirm import _get_guard_pass_codes
        new_codes = _get_guard_pass_codes(buy_targets)
        expected_codes = {bt.stock.code for bt in buy_targets if bt.stock.guard_pass}

        # EXPECTED BEHAVIOR: only guard_pass=True codes should be in subscription set
        assert new_codes == expected_codes, (
            f"Bug confirmed: subscription target includes guard_pass=False stocks. "
            f"new_codes={new_codes}, expected (guard_pass=True only)={expected_codes}, "
            f"unexpected (guard_pass=False)={new_codes - expected_codes}"
        )


# ── Test 3: guard_pass False→True 전환 시 해당 종목만 REG 발생 검증 ────────


class TestBug3GuardPassFalseToTrue:
    """Test 3: guard_pass False→True 전환 시 해당 종목만 REG 발생해야 함.

    **Validates: Requirements 1.3**

    Expected behavior: guard_pass가 False→True로 전환된 종목에 대해서만 REG 발생.
    Current bug: _buy_targets_changed()가 종목코드 집합만 비교하므로,
    guard_pass=False→True 전환이 발생해도 코드 집합이 동일하면 변경으로 감지하지 못한다.
    즉, 종목이 이미 buy_targets에 있었고 guard_pass만 False→True로 바뀐 경우,
    _buy_targets_changed()는 False를 반환하여 구독이 트리거되지 않는다.
    """

    @given(
        already_pass_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
        transitioning_code=stock_code_st,
    )
    @settings(max_examples=50, deadline=5000)
    def test_false_to_true_transition_detected_as_change(
        self,
        already_pass_codes: list[str],
        transitioning_code: str,
    ):
        """When a stock transitions guard_pass False→True (while remaining in buy_targets),
        the system should detect this as a change and trigger REG for that stock.

        Scenario:
        - prev: [A(pass=True), B(pass=True), C(pass=False)]  ← C in buy_targets but not subscribed
        - new:  [A(pass=True), B(pass=True), C(pass=True)]   ← C now passes guard
        - Expected: detect change, REG(C)
        - Bug: _buy_targets_changed() compares code sets only:
          prev_codes={A,B,C}, new_codes={A,B,C} → returns False → no subscription triggered!
        """
        assume(transitioning_code not in already_pass_codes)

        # prev buy_targets: A,B are guard_pass=True, C is guard_pass=False
        prev_targets = [make_buy_target(c, guard_pass=True) for c in already_pass_codes]
        prev_targets.append(make_buy_target(transitioning_code, guard_pass=False))

        # new buy_targets: same stocks, but C is now guard_pass=True
        new_targets = [make_buy_target(c, guard_pass=True) for c in already_pass_codes]
        new_targets.append(make_buy_target(transitioning_code, guard_pass=True))

        # guard_pass=True set changed: {A,B} → {A,B,C}
        prev_guard_pass_codes = {bt.stock.code for bt in prev_targets if bt.stock.guard_pass}
        new_guard_pass_codes = {bt.stock.code for bt in new_targets if bt.stock.guard_pass}
        assert prev_guard_pass_codes != new_guard_pass_codes  # sanity check

        # EXPECTED BEHAVIOR: _buy_targets_changed() should return True
        # because guard_pass=True set changed (C was added)
        # BUG: _buy_targets_changed() compares ALL codes: {A,B,C} == {A,B,C} → False
        result = _buy_targets_changed(prev_targets, new_targets)
        assert result is True, (
            f"Bug confirmed: _buy_targets_changed() returns False when guard_pass=True "
            f"set changed from {prev_guard_pass_codes} to {new_guard_pass_codes}. "
            f"Code sets are identical ({set(bt.stock.code for bt in prev_targets)}), "
            f"so the function misses the guard_pass transition."
        )


# ── Test 4: guard_pass True→False 전환 시 해당 종목만 REMOVE 발생 검증 ─────


class TestBug4GuardPassTrueToFalse:
    """Test 4: guard_pass True→False 전환 시 해당 종목만 REMOVE 발생해야 함.

    **Validates: Requirements 1.3**

    Expected behavior: guard_pass가 True→False로 전환된 종목에 대해서만 REMOVE 발생.
    Current behavior: _sync_0d_subscriptions()가 guard_pass를 무시하고 전체 코드 집합으로
    delta를 계산하므로, guard_pass=False로 전환된 종목이 여전히 구독 대상에 포함될 수 있다.
    """

    @given(
        remaining_pass_codes=st.lists(stock_code_st, min_size=1, max_size=3, unique=True),
        transitioning_code=stock_code_st,
    )
    @settings(max_examples=50, deadline=5000)
    def test_true_to_false_transition_only_removes_transitioning_stock(
        self,
        remaining_pass_codes: list[str],
        transitioning_code: str,
    ):
        """When a stock transitions guard_pass True→False, only that stock should get REMOVE.

        Scenario:
        - prev: [A(pass=True), B(pass=True), C(pass=True)] → subscribed={A,B,C}
        - new:  [A(pass=True), B(pass=True), C(pass=False)] ← C transitioned to False
        - Expected: REMOVE(C) only, no REG
        - Bug: If C is still in buy_targets (with guard_pass=False), _sync_0d_subscriptions
          still includes C in new_codes because it doesn't filter by guard_pass
        """
        assume(transitioning_code not in remaining_pass_codes)

        # prev state: all stocks were subscribed (all were guard_pass=True)
        prev_subscribed = set(remaining_pass_codes) | {transitioning_code}

        # new buy_targets: remaining are still pass=True, transitioning is now pass=False
        new_buy_targets = [make_buy_target(c, guard_pass=True) for c in remaining_pass_codes]
        new_buy_targets.append(make_buy_target(transitioning_code, guard_pass=False))

        # Test the actual subscription target calculation used by _sync_0d_subscriptions
        from app.services.engine_sector_confirm import _get_guard_pass_codes
        new_codes = _get_guard_pass_codes(new_buy_targets)

        # What it SHOULD do (expected):
        # new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}
        correct_new_codes = {bt.stock.code for bt in new_buy_targets if bt.stock.guard_pass}

        # Verify new_codes matches correct computation
        to_unreg = prev_subscribed - new_codes
        correct_to_unreg = prev_subscribed - correct_new_codes

        # EXPECTED BEHAVIOR: transitioning_code should be in to_unreg (REMOVE)
        assert correct_to_unreg == {transitioning_code}

        # After fix: new_codes should equal correct_new_codes (guard_pass=False excluded)
        assert new_codes == correct_new_codes, (
            f"Bug confirmed: _sync_0d_subscriptions includes guard_pass=False stock "
            f"'{transitioning_code}' in subscription target. "
            f"new_codes={new_codes}, "
            f"correct_new_codes={correct_new_codes}, "
            f"should_remove={new_codes - correct_new_codes}"
        )
