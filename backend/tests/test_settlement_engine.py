"""settlement_engine.py 단위 테스트 — 테스트모드 정산 엔진 로직 검증.

누적투자금/주문가능금액 관리, 매수/매도 체결 처리, 충전, 
Effective Buy Power 계산 로직을 검증.
_persist 및 _broadcast_delta는 mock로 격리.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from backend.app.core.constants import (
    BUY_COMMISSION,
    SELL_COMMISSION,
    SECURITIES_TAX,
)
from backend.app.services import settlement_engine
from backend.app.services.settlement_engine import (
    get_available_cash,
    get_accumulated_investment,
    get_orderable,
    get_initial_deposit,
    check_buy_power,
    reserve_buy_power,
    release_buy_power,
    on_buy_fill,
    on_sell_fill,
    charge,
    get_effective_buy_power,
    max_buy_qty_for_budget,
    reset,
)


# ── 픽스처 ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_engine():
    """각 테스트마다 모듈 상태를 초기화하고 _persist/_broadcast_delta를 mock."""
    orig_acc = settlement_engine._accumulated_investment
    orig_ord = settlement_engine._orderable
    orig_loaded = settlement_engine._loaded
    orig_init = settlement_engine._initial_deposit

    settlement_engine._accumulated_investment = 0
    settlement_engine._orderable = 0
    settlement_engine._loaded = True
    settlement_engine._initial_deposit = 10_000_000

    with patch.object(settlement_engine, "_persist", new_callable=AsyncMock) as mock_persist, \
         patch.object(settlement_engine, "_broadcast_delta", new_callable=AsyncMock) as mock_broadcast:
        yield mock_persist, mock_broadcast

    settlement_engine._accumulated_investment = orig_acc
    settlement_engine._orderable = orig_ord
    settlement_engine._loaded = orig_loaded
    settlement_engine._initial_deposit = orig_init


# ── _load (init 기능 통합) ─────────────────────────────────────────────────────

class TestLoad:
    @pytest.mark.asyncio
    async def test_load_initializes_when_not_loaded(self, fresh_engine):
        settlement_engine._loaded = False
        settlement_engine._accumulated_investment = 0
        settlement_engine._orderable = 0
        with patch("backend.app.services.settlement_engine.load_settlement_state",
                   new_callable=AsyncMock, return_value=None), \
             patch.object(settlement_engine, "_persist", new_callable=AsyncMock):
            await settlement_engine._load(initial_deposit=5_000_000)
        assert get_initial_deposit() == 5_000_000
        assert settlement_engine._accumulated_investment == 5_000_000
        assert settlement_engine._orderable == 5_000_000
        assert settlement_engine._loaded is True

    @pytest.mark.asyncio
    async def test_load_skips_when_already_loaded(self, fresh_engine):
        settlement_engine._loaded = True
        settlement_engine._accumulated_investment = 3_000_000
        settlement_engine._orderable = 2_000_000
        with patch("backend.app.services.settlement_engine.load_settlement_state",
                   new_callable=AsyncMock) as mock_load:
            await settlement_engine._load(initial_deposit=5_000_000)
        mock_load.assert_not_awaited()
        assert settlement_engine._accumulated_investment == 3_000_000
        assert settlement_engine._orderable == 2_000_000

    @pytest.mark.asyncio
    async def test_load_uses_settings_when_no_initial_deposit(self, fresh_engine):
        settlement_engine._loaded = False
        settlement_engine._accumulated_investment = 0
        settlement_engine._orderable = 0
        with patch("backend.app.services.settlement_engine.load_settlement_state",
                   new_callable=AsyncMock, return_value=None), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch.object(settlement_engine, "_persist", new_callable=AsyncMock):
            mock_state.integrated_system_settings_cache = {"test_virtual_deposit": 7_000_000}
            await settlement_engine._load()
        assert get_initial_deposit() == 7_000_000
        assert settlement_engine._accumulated_investment == 7_000_000
        assert settlement_engine._orderable == 7_000_000

    @pytest.mark.asyncio
    async def test_load_db_error_raises_exception(self, fresh_engine):
        settlement_engine._loaded = False
        settlement_engine._accumulated_investment = 0
        settlement_engine._orderable = 0
        with patch("backend.app.services.settlement_engine.load_settlement_state",
                   new_callable=AsyncMock, side_effect=Exception("DB error")):
            with pytest.raises(Exception, match="DB error"):
                await settlement_engine._load(initial_deposit=5_000_000)
        assert settlement_engine._loaded is False


# ── getters ────────────────────────────────────────────────────────────────────

class TestGetters:
    def test_get_available_cash_returns_orderable(self, fresh_engine):
        settlement_engine._orderable = 7_500_000
        assert get_available_cash() == 7_500_000

    def test_get_accumulated_investment(self, fresh_engine):
        settlement_engine._accumulated_investment = 10_000_000
        assert get_accumulated_investment() == 10_000_000

    def test_get_orderable(self, fresh_engine):
        settlement_engine._orderable = 3_000_000
        assert get_orderable() == 3_000_000

    def test_get_initial_deposit(self, fresh_engine):
        settlement_engine._initial_deposit = 8_000_000
        assert get_initial_deposit() == 8_000_000


# ── check_buy_power ────────────────────────────────────────────────────────────

class TestCheckBuyPower:
    def test_sufficient_cash_passes(self, fresh_engine):
        settlement_engine._orderable = 10_000_000
        ok, reason = check_buy_power(5_000_000)
        assert ok is True
        assert reason == ""

    def test_insufficient_cash_fails(self, fresh_engine):
        settlement_engine._orderable = 1_000_000
        ok, reason = check_buy_power(5_000_000)
        assert ok is False
        assert "주문가능금액 부족" in reason

    def test_exact_amount_with_commission_fails(self, fresh_engine):
        settlement_engine._orderable = 5_000_000
        # cost = 5_000_000 + round(5_000_000 * 0.00015) = 5_000_000 + 750 = 5_000_750
        ok, reason = check_buy_power(5_000_000)
        assert ok is False

    def test_amount_plus_commission_within_limit_passes(self, fresh_engine):
        settlement_engine._orderable = 5_001_000
        ok, reason = check_buy_power(5_000_000)
        assert ok is True

    def test_daily_limit_reduces_effective_power(self, fresh_engine):
        settlement_engine._orderable = 10_000_000
        ok, reason = check_buy_power(3_000_000, daily_limit=5_000_000, daily_spent=3_000_000)
        # effective = min(10_000_000, 5_000_000 - 3_000_000) = 2_000_000
        # cost = 3_000_000 + 450 = 3_000_450 > 2_000_000
        assert ok is False

    def test_daily_limit_zero_means_unlimited(self, fresh_engine):
        settlement_engine._orderable = 10_000_000
        ok, reason = check_buy_power(5_000_000, daily_limit=0, daily_spent=0)
        assert ok is True

    def test_commission_calculation(self, fresh_engine):
        settlement_engine._orderable = 100_000
        # 50_000 + round(50_000 * 0.00015) = 50_000 + 8 = 50_008
        ok, _ = check_buy_power(50_000)
        assert ok is True
        # 99_999 + round(99_999 * 0.00015) = 99_999 + 15 = 100_014 > 100_000
        ok, _ = check_buy_power(99_999)
        assert ok is False


# ── reserve_buy_power (TOCTOU 경쟁 상태 방지) ──────────────────────────────────

class TestReserveBuyPower:
    """reserve_buy_power: 검증 + 즉시 차감 원자적 수행 (TOCTOU 경쟁 상태 방지)."""

    @pytest.mark.asyncio
    async def test_reserve_success_deducts_immediately(self, fresh_engine):
        """검증 통과 시 _orderable에서 즉시 차감."""
        settlement_engine._orderable = 10_000_000
        ok, reason, cost = await reserve_buy_power(5_000_000)
        assert ok is True
        assert reason == ""
        expected_cost = 5_000_000 + round(5_000_000 * BUY_COMMISSION)
        assert cost == expected_cost
        assert settlement_engine._orderable == 10_000_000 - expected_cost

    @pytest.mark.asyncio
    async def test_reserve_fail_does_not_deduct(self, fresh_engine):
        """검증 실패 시 _orderable 변동 없음."""
        settlement_engine._orderable = 100_000
        ok, reason, cost = await reserve_buy_power(5_000_000)
        assert ok is False
        assert "주문가능금액 부족" in reason
        assert cost == 0
        assert settlement_engine._orderable == 100_000

    @pytest.mark.asyncio
    async def test_reserve_persists_and_broadcasts(self, fresh_engine):
        """성공 시 영속화 + 브로드캐스트 호출."""
        mock_persist, mock_broadcast = fresh_engine
        settlement_engine._orderable = 10_000_000
        await reserve_buy_power(5_000_000)
        mock_persist.assert_awaited_once()
        mock_broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reserve_fail_no_persist(self, fresh_engine):
        """실패 시 영속화/브로드캐스트 호출 안 함."""
        mock_persist, mock_broadcast = fresh_engine
        settlement_engine._orderable = 100
        await reserve_buy_power(5_000_000)
        mock_persist.assert_not_awaited()
        mock_broadcast.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reserve_with_daily_limit_blocks_when_exceeded(self, fresh_engine):
        """일일 한도 초과 시 차단 (effective = min(orderable, daily_limit - daily_spent))."""
        settlement_engine._orderable = 10_000_000
        # effective = min(10_000_000, 5_000_000 - 3_000_000) = 2_000_000
        # cost = 3_000_000 + 450 = 3_000_450 > 2_000_000 → 실패
        ok, reason, cost = await reserve_buy_power(3_000_000, daily_limit=5_000_000, daily_spent=3_000_000)
        assert ok is False
        assert cost == 0

    @pytest.mark.asyncio
    async def test_reserve_with_daily_limit_allows_when_within(self, fresh_engine):
        """일일 한도 내에서는 차감 허용."""
        settlement_engine._orderable = 10_000_000
        # effective = min(10_000_000, 5_000_000 - 0) = 5_000_000
        # cost = 1_000_000 + 150 = 1_000_150 <= 5_000_000 → 성공
        ok, _, cost = await reserve_buy_power(1_000_000, daily_limit=5_000_000, daily_spent=0)
        assert ok is True
        assert cost == 1_000_000 + round(1_000_000 * BUY_COMMISSION)

    @pytest.mark.asyncio
    async def test_reserve_prevents_toctou_race(self, fresh_engine):
        """TOCTOU 핵심 검증: 두 번째 reserve가 첫 번째 차감 후 잔액으로 검증."""
        settlement_engine._orderable = 5_000_000
        # 첫 번째 매수: 4_000_000원 예약
        ok1, _, cost1 = await reserve_buy_power(4_000_000)
        assert ok1 is True
        after_first = settlement_engine._orderable
        # 두 번째 매수: 남은 잔액으로 검증 (check_buy_power였다면 원래 잔액으로 검증했을 것)
        ok2, _, cost2 = await reserve_buy_power(4_000_000)
        # 남은 잔액 ≈ 994_000원으로는 4_000_000원 매수 불가
        assert ok2 is False
        assert settlement_engine._orderable == after_first


# ── release_buy_power (롤백) ──────────────────────────────────────────────────

class TestReleaseBuyPower:
    """release_buy_power: 사전 차감 롤백 (주문 실패 시 정합성 보장)."""

    @pytest.mark.asyncio
    async def test_release_restores_orderable(self, fresh_engine):
        """롤백 시 _orderable에 차감액 복원."""
        settlement_engine._orderable = 5_000_000
        await release_buy_power(1_000_000)
        assert settlement_engine._orderable == 6_000_000

    @pytest.mark.asyncio
    async def test_release_zero_no_change(self, fresh_engine):
        """0원 롤백 시 변동 없음."""
        settlement_engine._orderable = 5_000_000
        await release_buy_power(0)
        assert settlement_engine._orderable == 5_000_000

    @pytest.mark.asyncio
    async def test_release_negative_no_change(self, fresh_engine):
        """음수 롤백 시 변동 없음."""
        settlement_engine._orderable = 5_000_000
        await release_buy_power(-100)
        assert settlement_engine._orderable == 5_000_000

    @pytest.mark.asyncio
    async def test_release_persists_and_broadcasts(self, fresh_engine):
        """롤백 시 영속화 + 브로드캐스트."""
        mock_persist, mock_broadcast = fresh_engine
        settlement_engine._orderable = 5_000_000
        await release_buy_power(1_000_000)
        mock_persist.assert_awaited_once()
        mock_broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reserve_then_release_roundtrip(self, fresh_engine):
        """예약 → 롤백 시 원래 잔액으로 복원."""
        original = 10_000_000
        settlement_engine._orderable = original
        ok, _, cost = await reserve_buy_power(3_000_000)
        assert ok is True
        assert settlement_engine._orderable == original - cost
        await release_buy_power(cost)
        assert settlement_engine._orderable == original


# ── on_buy_fill ────────────────────────────────────────────────────────────────

class TestOnBuyFill:
    @pytest.mark.asyncio
    async def test_buy_reduces_orderable(self, fresh_engine):
        mock_persist, mock_broadcast = fresh_engine
        settlement_engine._orderable = 10_000_000
        result = await on_buy_fill(70_000, 10)
        cost = 700_000 + round(700_000 * BUY_COMMISSION)
        assert result == 10_000_000 - cost
        assert settlement_engine._orderable == 10_000_000 - cost

    @pytest.mark.asyncio
    async def test_buy_does_not_change_accumulated_investment(self, fresh_engine):
        settlement_engine._accumulated_investment = 10_000_000
        settlement_engine._orderable = 10_000_000
        await on_buy_fill(70_000, 10)
        assert settlement_engine._accumulated_investment == 10_000_000

    @pytest.mark.asyncio
    async def test_buy_persists_and_broadcasts(self, fresh_engine):
        mock_persist, mock_broadcast = fresh_engine
        settlement_engine._orderable = 10_000_000
        await on_buy_fill(70_000, 10)
        mock_persist.assert_awaited_once()
        mock_broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_buy_floor_at_zero(self, fresh_engine):
        settlement_engine._orderable = 100
        result = await on_buy_fill(70_000, 10)
        assert result == 0
        assert settlement_engine._orderable == 0


# ── on_sell_fill ───────────────────────────────────────────────────────────────

class TestOnSellFill:
    @pytest.mark.asyncio
    async def test_sell_increases_orderable(self, fresh_engine):
        settlement_engine._orderable = 5_000_000
        result = await on_sell_fill(80_000, 10, "005930", "삼성전자")
        gross = 800_000
        net = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
        assert result == 5_000_000 + net
        assert settlement_engine._orderable == 5_000_000 + net

    @pytest.mark.asyncio
    async def test_sell_does_not_change_accumulated_investment(self, fresh_engine):
        settlement_engine._accumulated_investment = 10_000_000
        settlement_engine._orderable = 5_000_000
        await on_sell_fill(80_000, 10, "005930", "삼성전자")
        assert settlement_engine._accumulated_investment == 10_000_000

    @pytest.mark.asyncio
    async def test_sell_persists_and_broadcasts(self, fresh_engine):
        mock_persist, mock_broadcast = fresh_engine
        settlement_engine._orderable = 5_000_000
        await on_sell_fill(80_000, 10, "005930", "삼성전자")
        mock_persist.assert_awaited_once()
        mock_broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sell_net_proceeds_calculation(self, fresh_engine):
        settlement_engine._orderable = 0
        await on_sell_fill(100_000, 1, "A001", "테스트")
        gross = 100_000
        expected_net = gross - round(gross * SECURITIES_TAX) - round(gross * SELL_COMMISSION)
        assert settlement_engine._orderable == expected_net


# ── charge ─────────────────────────────────────────────────────────────────────

class TestCharge:
    @pytest.mark.asyncio
    async def test_charge_increases_both(self, fresh_engine):
        settlement_engine._accumulated_investment = 5_000_000
        settlement_engine._orderable = 3_000_000
        result = await charge(2_000_000)
        assert settlement_engine._accumulated_investment == 7_000_000
        assert settlement_engine._orderable == 5_000_000
        assert result == 5_000_000

    @pytest.mark.asyncio
    async def test_charge_zero_amount_no_change(self, fresh_engine):
        settlement_engine._accumulated_investment = 5_000_000
        settlement_engine._orderable = 3_000_000
        result = await charge(0)
        assert settlement_engine._accumulated_investment == 5_000_000
        assert settlement_engine._orderable == 3_000_000
        assert result == 3_000_000

    @pytest.mark.asyncio
    async def test_charge_negative_amount_no_change(self, fresh_engine):
        settlement_engine._accumulated_investment = 5_000_000
        settlement_engine._orderable = 3_000_000
        await charge(-1_000_000)
        assert settlement_engine._accumulated_investment == 5_000_000
        assert settlement_engine._orderable == 3_000_000

    @pytest.mark.asyncio
    async def test_charge_persists_and_broadcasts(self, fresh_engine):
        mock_persist, mock_broadcast = fresh_engine
        settlement_engine._orderable = 0
        await charge(1_000_000)
        mock_persist.assert_awaited_once()
        mock_broadcast.assert_awaited_once()


# ── get_effective_buy_power ────────────────────────────────────────────────────

class TestGetEffectiveBuyPower:
    def test_no_daily_limit_returns_orderable(self, fresh_engine):
        settlement_engine._orderable = 8_000_000
        assert get_effective_buy_power(0, 0) == 8_000_000

    def test_daily_limit_above_orderable_returns_orderable(self, fresh_engine):
        settlement_engine._orderable = 5_000_000
        assert get_effective_buy_power(10_000_000, 0) == 5_000_000

    def test_daily_limit_below_orderable_returns_remainder(self, fresh_engine):
        settlement_engine._orderable = 10_000_000
        assert get_effective_buy_power(8_000_000, 3_000_000) == 5_000_000

    def test_daily_spent_exceeds_limit_returns_zero(self, fresh_engine):
        settlement_engine._orderable = 10_000_000
        assert get_effective_buy_power(5_000_000, 6_000_000) == 0

    def test_daily_spent_equals_limit_returns_zero(self, fresh_engine):
        settlement_engine._orderable = 10_000_000
        assert get_effective_buy_power(5_000_000, 5_000_000) == 0


# ── reset ──────────────────────────────────────────────────────────────────────

class TestReset:
    @pytest.mark.asyncio
    async def test_reset_sets_all_to_initial_deposit(self, fresh_engine):
        settlement_engine._accumulated_investment = 3_000_000
        settlement_engine._orderable = 1_000_000
        await reset(15_000_000)
        assert settlement_engine._accumulated_investment == 15_000_000
        assert settlement_engine._orderable == 15_000_000
        assert settlement_engine._initial_deposit == 15_000_000

    @pytest.mark.asyncio
    async def test_reset_persists_and_broadcasts(self, fresh_engine):
        mock_persist, mock_broadcast = fresh_engine
        await reset(10_000_000)
        mock_persist.assert_awaited_once()
        mock_broadcast.assert_awaited_once()


# ── 수수료/세금 상수 검증 ─────────────────────────────────────────────────────

class TestConstants:
    def test_buy_commission_rate(self):
        assert BUY_COMMISSION == 0.00015

    def test_sell_commission_rate(self):
        assert SELL_COMMISSION == 0.00015

    def test_securities_tax_rate(self):
        assert SECURITIES_TAX == 0.002


# ── max_buy_qty_for_budget 헬퍼 단위 테스트 (P10 SSOT / P22 정합성) ────────────

class TestMaxBuyQtyForBudget:
    """예산 내 최대 매수 수량(수수료 포함) 헬퍼 검증.
    reserve_buy_power의 cost 공식(price*qty + round(price*qty*BUY_COMMISSION))과
    정합되는지 검증 — trading.py buy_qty 계산과 buy_order_executor가 동일 기준으로 호출.
    """

    def test_zero_price_returns_zero(self):
        assert max_buy_qty_for_budget(0, 1_000_000, is_test=True) == 0

    def test_zero_budget_returns_zero(self):
        assert max_buy_qty_for_budget(70_000, 0, is_test=True) == 0

    def test_negative_inputs_returns_zero(self):
        assert max_buy_qty_for_budget(-1, -1, is_test=True) == 0

    def test_test_mode_exact_fit_no_fee_overflow(self):
        """예산이 딱 맞을 때 수수료 포함 후에도 수량 유지.
        price=70000, budget=980147 → 14주 cost=980147 (정확히 일치).
        """
        budget = 14 * 70_000 + round(14 * 70_000 * BUY_COMMISSION)
        assert max_buy_qty_for_budget(70_000, budget, is_test=True) == 14

    def test_test_mode_fee_overflow_reduces_qty(self):
        """수수료 초과 시 1주 감소.
        price=70000, budget=980146 (1원 부족) → 14주 cost=980147 > 980146 → 13주.
        """
        budget = 14 * 70_000 + round(14 * 70_000 * BUY_COMMISSION) - 1
        assert max_buy_qty_for_budget(70_000, budget, is_test=True) == 13

    def test_test_mode_one_share_only(self):
        """예산이 1주+수수료는 감당하지만 2주는 안 되는 경우."""
        budget = 70_000 + round(70_000 * BUY_COMMISSION)
        assert max_buy_qty_for_budget(70_000, budget, is_test=True) == 1

    def test_test_mode_cannot_afford_one_share(self):
        """예산이 1주+수수료보다 적으면 0."""
        budget = 70_000 + round(70_000 * BUY_COMMISSION) - 1
        assert max_buy_qty_for_budget(70_000, budget, is_test=True) == 0

    def test_real_mode_excludes_fee(self):
        """실전모드는 수수료 미적용 — budget // price."""
        # 14*70000=980000, 14*70000+fee=980147 > 980000이지만 실전은 무시
        assert max_buy_qty_for_budget(70_000, 980_000, is_test=False) == 14

    @pytest.mark.asyncio
    async def test_consistent_with_reserve_buy_power(self, fresh_engine):
        """헬퍼가 반환한 수량으로 reserve_buy_power 호출 시 반드시 성공해야 함 (P22 정합성)."""
        mock_persist, mock_broadcast = fresh_engine
        # 주문가능금액을 1_000_000으로 설정
        settlement_engine._orderable = 1_000_000
        price = 70_000
        qty = max_buy_qty_for_budget(price, 1_000_000, is_test=True)
        assert qty > 0
        ok, reason, cost = await reserve_buy_power(price * qty, 0, 0)
        assert ok is True, f"reserve_buy_power 거부: {reason}"
        # 헬퍼가 계산한 qty로 실제 cost가 예산 이내인지 재확인
        assert cost == price * qty + round(price * qty * BUY_COMMISSION)
        assert cost <= 1_000_000
