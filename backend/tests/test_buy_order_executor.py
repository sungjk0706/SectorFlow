"""buy_order_executor.py 단위 테스트 — 매수 주문 실행 경로 검증.

evaluate_buy_candidates의 게이트 체크, 매수 시도, State Gate 동작을 검증.
engine_state 및 관련 모듈은 mock로 격리.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services import buy_order_executor
from backend.app.services.buy_order_executor import evaluate_buy_candidates
from backend.app.services.trading import (
    BUY_REJECT_RISE_GUARD, BUY_REJECT_AUTO_BUY_OFF, BUY_REJECT_QTY_ZERO,
    BUY_REJECT_RISK_LOSS_RATE, BUY_REJECT_RISK_CONSEC_LOSS,
    BUY_REJECT_MAX_HOLDING, BUY_REJECT_DAILY_LIMIT, BUY_REJECT_RISK_CASH,
    BUY_REJECT_BUY_AMT_ZERO, BUY_REJECT_REASON_TEXT,
    BUY_REJECT_BUY_TIME_OUT, BUY_REJECT_MASTER_OFF,
)
from backend.app.domain.models import StockScore, SectorSummary, BuyTarget


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _stock(code="005930", guard_pass=True, cur_price=70000, sector="반도체", name="삼성전자", nxt_enable=False,
           boost_high_triggered=False, boost_order_ratio_triggered=False,
           boost_news_triggered=False, boost_program_triggered=False):
    s = StockScore(
        code=code, name=name, sector=sector,
        change_rate=1.0, trade_amount=1_000_000_000,
        avg_amt_5d=40, strength=100.0,
        cur_price=cur_price, change=700, market_type="0", nxt_enable=nxt_enable,
        guard_pass=guard_pass,
        boost_high_triggered=boost_high_triggered,
        boost_order_ratio_triggered=boost_order_ratio_triggered,
        boost_news_triggered=boost_news_triggered,
        boost_program_triggered=boost_program_triggered,
    )
    return s


def _sector_summary(stocks=None, buy_targets=None):
    if stocks is None:
        stocks = [_stock()]
    if buy_targets is None:
        buy_targets = [BuyTarget(rank=1, sector_rank=1, stock=stocks[0])]
    return SectorSummary(
        sectors=[],
        buy_targets=buy_targets,
        blocked_targets=[],
        version=1,
    )


def _default_settings(**overrides):
    s = {
        "test_mode_on": True,
        "max_stock_cnt": 5,
        "max_stock_cnt_on": True,
        "buy_amt": 1_000_000,
        "buy_amt_on": True,
        "max_daily_total_buy_amt": 0,
        "max_daily_total_buy_on": False,
        "buy_interval_on": False,
        "buy_interval_sec": 30,
        "time_scheduler_on": True,
        "auto_buy_on": True,
        "buy_time_start": "09:00",
        "buy_time_end": "15:30",
    }
    s.update(overrides)
    return s


# ── 픽스처 ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_state():
    """engine_state.state mock — 각 테스트마다 초기화."""
    mock_state = MagicMock()
    mock_state.running = True
    mock_state.auto_trade = MagicMock()
    mock_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
    mock_state.auto_trade._daily_buy_spent = 0
    mock_state.auto_trade._bought_today = {}
    mock_state.auto_trade._ensure_daily_buy_counter = AsyncMock()
    mock_state.sector_summary_cache = _sector_summary()
    mock_state.integrated_system_settings_cache = _default_settings()
    mock_state.access_token = "test_token"
    mock_state._last_global_buy_ts = 0.0
    return mock_state


@pytest.fixture
def reset_cash_gate():
    """_cash_insufficient 플래그 및 스냅샷 초기화 + notify_buy_targets_update mock."""
    buy_order_executor._cash_insufficient = False
    buy_order_executor._last_global_snapshot = None
    with patch("backend.app.services.engine_account_notify.notify_buy_targets_update",
               new_callable=AsyncMock) as _mock_notify:
        yield _mock_notify
    buy_order_executor._cash_insufficient = False
    buy_order_executor._last_global_snapshot = None


# ── 조기 반환 게이트 ───────────────────────────────────────────────────────────

class TestEarlyReturnGates:
    @pytest.mark.asyncio
    async def test_not_running_returns_early(self, fresh_state, reset_cash_gate):
        fresh_state.running = False
        with patch("backend.app.services.engine_state.state", fresh_state):
            await evaluate_buy_candidates()
        # auto_trade.execute_buy should not be called
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_auto_trade_returns_early(self, fresh_state, reset_cash_gate):
        fresh_state.auto_trade = None
        with patch("backend.app.services.engine_state.state", fresh_state):
            await evaluate_buy_candidates()

    @pytest.mark.asyncio
    async def test_no_sector_summary_returns_early(self, fresh_state, reset_cash_gate):
        fresh_state.sector_summary_cache = None
        with patch("backend.app.services.engine_state.state", fresh_state):
            await evaluate_buy_candidates()

    @pytest.mark.asyncio
    async def test_empty_buy_targets_returns_early(self, fresh_state, reset_cash_gate):
        fresh_state.sector_summary_cache = SectorSummary(
            sectors=[], buy_targets=[], blocked_targets=[], version=1,
        )
        with patch("backend.app.services.engine_state.state", fresh_state):
            await evaluate_buy_candidates()

    @pytest.mark.asyncio
    async def test_auto_buy_not_effective_returns_early(self, fresh_state, reset_cash_gate):
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=False), \
             patch("backend.app.services.buy_order_executor.auto_buy_reject_reason",
                   return_value=BUY_REJECT_BUY_TIME_OUT):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()
        # 차단 사유가 "원인" 컬럼에 표시되는지 검증 (P21 사용자 투명성)
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_BUY_TIME_OUT]
        reset_cash_gate.assert_awaited()

    @pytest.mark.asyncio
    async def test_auto_buy_time_out_marks_reject_reason(self, fresh_state, reset_cash_gate):
        """자동매수 시간외 → 모든 매수 후보 "원인" 컬럼에 "자동매수 시간외" 표시 (P21)."""
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=False), \
             patch("backend.app.services.buy_order_executor.auto_buy_reject_reason",
                   return_value=BUY_REJECT_BUY_TIME_OUT):
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == "자동매수 시간외"
        reset_cash_gate.assert_awaited()

    @pytest.mark.asyncio
    async def test_auto_buy_off_marks_reject_reason(self, fresh_state, reset_cash_gate):
        """자동매수 OFF(auto_buy_on=False) → "원인" 컬럼에 "자동매수 OFF" 표시 (P21)."""
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=False), \
             patch("backend.app.services.buy_order_executor.auto_buy_reject_reason",
                   return_value=BUY_REJECT_AUTO_BUY_OFF):
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == "자동매수 OFF"
        reset_cash_gate.assert_awaited()

    @pytest.mark.asyncio
    async def test_master_off_marks_reject_reason(self, fresh_state, reset_cash_gate):
        """자동매매 OFF(time_scheduler_on=False) → "원인" 컬럼에 "자동매매 OFF" 표시 (P21)."""
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=False), \
             patch("backend.app.services.buy_order_executor.auto_buy_reject_reason",
                   return_value=BUY_REJECT_MASTER_OFF):
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == "자동매매 OFF"
        reset_cash_gate.assert_awaited()

    @pytest.mark.asyncio
    async def test_holding_count_exceeds_max_returns_early(self, fresh_state, reset_cash_gate):
        fresh_state.integrated_system_settings_cache = _default_settings(max_stock_cnt=1)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[{"qty": 1}, {"qty": 2}]):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_buy_amt_zero_returns_early(self, fresh_state, reset_cash_gate):
        fresh_state.integrated_system_settings_cache = _default_settings(buy_amt=0)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_buy_amt_on_false_skips_buy_amt_check(self, fresh_state, reset_cash_gate):
        # buy_amt_on=False → buy_amt=0이어도 차단하지 않음 (한도 없음)
        fresh_state.integrated_system_settings_cache = _default_settings(buy_amt_on=False, buy_amt=0)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 500_000
            await evaluate_buy_candidates()
        # execute_buy가 호출되어야 함 (buy_amt_on=False로 차단되지 않음)
        fresh_state.auto_trade.execute_buy.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_stock_cnt_on_false_skips_holding_check(self, fresh_state, reset_cash_gate):
        # max_stock_cnt_on=False → 보유수 >= max_stock_cnt여도 차단하지 않음
        fresh_state.integrated_system_settings_cache = _default_settings(max_stock_cnt_on=False, max_stock_cnt=1)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[{"qty": 1}, {"qty": 2}]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 500_000
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_called_once()

    @pytest.mark.asyncio
    async def test_daily_limit_exceeded_returns_early(self, fresh_state, reset_cash_gate):
        fresh_state.integrated_system_settings_cache = _default_settings(
            max_daily_total_buy_on=True, max_daily_total_buy_amt=5_000_000,
        )
        fresh_state.auto_trade._daily_buy_spent = 5_000_000
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()


# ── State Gate (주문가능 금액 부족) ────────────────────────────────────────────

class TestCashInsufficientGate:
    @pytest.mark.asyncio
    async def test_zero_cash_sets_gate_and_returns(self, fresh_state, reset_cash_gate):
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=0):
            await evaluate_buy_candidates()
        assert buy_order_executor._cash_insufficient is True
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_positive_cash_clears_gate(self, fresh_state, reset_cash_gate):
        buy_order_executor._cash_insufficient = True
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        assert buy_order_executor._cash_insufficient is False


# ── 매수 간격 게이트 ───────────────────────────────────────────────────────────

class TestBuyIntervalGate:
    @pytest.mark.asyncio
    async def test_buy_interval_blocks_within_period(self, fresh_state, reset_cash_gate):
        import time as _time
        fresh_state.integrated_system_settings_cache = _default_settings(
            buy_interval_on=True, buy_interval_sec=300,
        )
        fresh_state._last_global_buy_ts = _time.time()
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_buy_interval_passes_after_period(self, fresh_state, reset_cash_gate):
        import time as _time
        fresh_state.integrated_system_settings_cache = _default_settings(
            buy_interval_on=True, buy_interval_sec=60,
        )
        fresh_state._last_global_buy_ts = _time.time() - 120  # 120초 전 (간격 60초 초과)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_buy_interval_off_passes(self, fresh_state, reset_cash_gate):
        import time as _time
        fresh_state.integrated_system_settings_cache = _default_settings(
            buy_interval_on=False, buy_interval_sec=300,
        )
        fresh_state._last_global_buy_ts = _time.time()  # 간격 내라도 토글 OFF면 통과
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_buy_interval_zero_sec_passes(self, fresh_state, reset_cash_gate):
        import time as _time
        fresh_state.integrated_system_settings_cache = _default_settings(
            buy_interval_on=True, buy_interval_sec=0,
        )
        fresh_state._last_global_buy_ts = _time.time()  # 간격 내라도 0초=비활성이면 통과
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_awaited_once()


# ── 매수 실행 경로 ─────────────────────────────────────────────────────────────

class TestBuyExecution:
    @pytest.mark.asyncio
    async def test_calls_execute_buy_for_first_target(self, fresh_state, reset_cash_gate):
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_guard_failed_stock(self, fresh_state, reset_cash_gate):
        s_blocked = _stock(code="A001", guard_pass=False)
        s_pass = _stock(code="A002", guard_pass=True)
        fresh_state.sector_summary_cache = SectorSummary(
            sectors=[],
            buy_targets=[
                BuyTarget(rank=1, sector_rank=1, stock=s_blocked),
                BuyTarget(rank=2, sector_rank=1, stock=s_pass),
            ],
            blocked_targets=[],
            version=1,
        )
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        # Should only call execute_buy for A002 (guard_pass=True), not A001
        call_args = fresh_state.auto_trade.execute_buy.call_args
        assert call_args.args[0] == "A002"

    @pytest.mark.asyncio
    async def test_after_hours_blocks_non_nxt_stock(self, fresh_state, reset_cash_gate):
        s = _stock(code="A001", nxt_enable=False)
        fresh_state.sector_summary_cache = _sector_summary(
            stocks=[s],
            buy_targets=[BuyTarget(rank=1, sector_rank=1, stock=s)],
        )
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=True):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_after_hours_allows_nxt_stock(self, fresh_state, reset_cash_gate):
        s = _stock(code="A001", nxt_enable=True)
        fresh_state.sector_summary_cache = _sector_summary(
            stocks=[s],
            buy_targets=[BuyTarget(rank=1, sector_rank=1, stock=s)],
        )
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zero_price_breaks_loop(self, fresh_state, reset_cash_gate):
        s = _stock(code="A001", cur_price=0)
        fresh_state.sector_summary_cache = _sector_summary(
            stocks=[s],
            buy_targets=[BuyTarget(rank=1, sector_rank=1, stock=s)],
        )
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_buy_exception_does_not_crash(self, fresh_state, reset_cash_gate):
        fresh_state.auto_trade.execute_buy = AsyncMock(side_effect=Exception("test error"))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            # Should not raise
            await evaluate_buy_candidates()


# ── 전역 조건 스냅샷 캐싱 ──────────────────────────────────────────────────────

class TestGlobalSnapshotCache:
    """전역 조건 스냅샷: 조건 변화 없으면 매수 시도 스킵, 무효화 시 재허용."""

    @pytest.mark.asyncio
    async def test_second_call_with_same_conditions_skipped(self, fresh_state, reset_cash_gate):
        """동일 전역 조건으로 두 번째 호출 시 execute_buy 호출되지 않음."""
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_RISE_GUARD))
        patches = [
            patch("backend.app.services.engine_state.state", fresh_state),
            patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True),
            patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True),
            patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                  return_value=[]),
            patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000),
            patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False),
        ]
        for p in patches:
            p.start()
        try:
            # 1차 호출 — 매수 시도 발생 (execute_buy 반환 False = 차단)
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 1

            # execute_buy mock 리셋
            fresh_state.auto_trade.execute_buy.reset_mock()

            # 2차 호출 — 동일 조건 → 스킵
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 0
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_invalidate_allows_re_evaluation(self, fresh_state, reset_cash_gate):
        """invalidate_buy_snapshot 호출 후에는 매수 재시도 허용."""
        patches = [
            patch("backend.app.services.engine_state.state", fresh_state),
            patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True),
            patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True),
            patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                  return_value=[]),
            patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000),
            patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False),
        ]
        for p in patches:
            p.start()
        try:
            # 1차 호출 — 매수 시도
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 1

            fresh_state.auto_trade.execute_buy.reset_mock()

            # 스냅샷 무효화
            buy_order_executor.invalidate_buy_snapshot()

            # 2차 호출 — 무효화 후 재허용
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 1
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_different_top_code_allows_re_evaluation(self, fresh_state, reset_cash_gate):
        """1순위 종목이 변경되면 스냅샷이 달라져 매수 재시도 허용."""
        s1 = _stock(code="A001")
        fresh_state.sector_summary_cache = _sector_summary(
            stocks=[s1],
            buy_targets=[BuyTarget(rank=1, sector_rank=1, stock=s1)],
        )
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        patches = [
            patch("backend.app.services.engine_state.state", fresh_state),
            patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True),
            patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True),
            patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                  return_value=[]),
            patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000),
            patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False),
        ]
        for p in patches:
            p.start()
        try:
            # 1차 호출 — A001 매수 시도
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 1

            fresh_state.auto_trade.execute_buy.reset_mock()

            # 1순위 종목 변경: A001 → A002
            s2 = _stock(code="A002")
            fresh_state.sector_summary_cache = _sector_summary(
                stocks=[s2],
                buy_targets=[BuyTarget(rank=1, sector_rank=1, stock=s2)],
            )

            # 2차 호출 — buyable_codes 변경 → 스냅샷 상이 → 매수 시도
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 1
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_same_buyable_codes_different_order_retries(self, fresh_state, reset_cash_gate):
        """동일 매수 가능 종목 집합의 정렬 순서가 바뀐 경우 재시도 (rank 변동 감지)."""
        s1 = _stock(code="A001")
        s2 = _stock(code="A002")
        fresh_state.sector_summary_cache = SectorSummary(
            sectors=[],
            buy_targets=[
                BuyTarget(rank=1, sector_rank=1, stock=s1),
                BuyTarget(rank=2, sector_rank=1, stock=s2),
            ],
            blocked_targets=[],
            version=1,
        )
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_RISE_GUARD))
        patches = [
            patch("backend.app.services.engine_state.state", fresh_state),
            patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True),
            patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True),
            patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                  return_value=[]),
            patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000),
            patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False),
        ]
        for p in patches:
            p.start()
        try:
            # 1차 호출 — A001 1순위 종목별 차단(등락률) → 차순위 A002 시도 → 또 차단
            # 2세션 차순위 시도 알고리즘: 종목별 차단 시 continue → 2회 호출
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 2

            fresh_state.auto_trade.execute_buy.reset_mock()

            # 정렬 순서만 변경: A002 → A001 (buyable_codes는 동일, rank는 변동)
            fresh_state.sector_summary_cache = SectorSummary(
                sectors=[],
                buy_targets=[
                    BuyTarget(rank=1, sector_rank=1, stock=s2),
                    BuyTarget(rank=2, sector_rank=1, stock=s1),
                ],
                blocked_targets=[],
                version=1,
            )

            # 2차 호출 — rank 변동 → 스냅샷 불일치 → 재시도 (P11 이벤트 기반)
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 2
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_successful_buy_invalidates_snapshot(self, fresh_state, reset_cash_gate):
        """매수 성공 후 스냅샷이 무효화되어 다음 호출 시 재시도 허용."""
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        patches = [
            patch("backend.app.services.engine_state.state", fresh_state),
            patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True),
            patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True),
            patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                  return_value=[]),
            patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000),
            patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False),
        ]
        for p in patches:
            p.start()
        try:
            # 1차 호출 — 매수 성공
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 1

            # 매수 성공 후 스냅샷이 무효화되었는지 확인
            assert buy_order_executor._last_global_snapshot is None

            fresh_state.auto_trade.execute_buy.reset_mock()

            # 2차 호출 — 스냅샷 무효화 상태 → 재시도
            await evaluate_buy_candidates()
            assert fresh_state.auto_trade.execute_buy.await_count == 1
        finally:
            for p in patches:
                p.stop()


# ── 가격 기반 사전 필터링 (orderable vs cur_price) ──────────────────────────

class TestPriceBasedFiltering:
    """_buyable_codes가 orderable/cur_price를 기반으로 종목을 필터링하는지 검증.
    execute_buy 호출 전에 매수 불가 종목을 차단하여 "매수 시도" 로그 후 차단되는
    불필요한 호출을 제거 (P10 SSOT, P21 사용자 투명성).
    """

    @pytest.mark.asyncio
    async def test_orderable_less_than_price_blocks_execute_buy(self, fresh_state, reset_cash_gate):
        """주문가능금액이 종목 가격보다 적으면 execute_buy 호출 안 됨."""
        # cur_price=70000, 테스트모드 슬리피지 적용 시 est_price=70100
        # available=50_000 < 70100 → _buyable_codes에서 제외
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 50_000
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_orderable_greater_than_price_allows_execute_buy(self, fresh_state, reset_cash_gate):
        """주문가능금액이 종목 가격보다 크면 execute_buy 호출됨."""
        # cur_price=70000, est_price=70100
        # available=10_000_000 >= 70100 → _buyable_codes에 포함
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_called_once()

    @pytest.mark.asyncio
    async def test_buy_amt_on_false_orderable_less_than_price_blocks(self, fresh_state, reset_cash_gate):
        """buy_amt_on=False일 때도 orderable < cur_price이면 execute_buy 호출 안 됨."""
        # buy_amt_on=False → _effective_buy_amt=None → _max_for_code=available
        # available=50_000 < est_price=70100 → 차단
        fresh_state.integrated_system_settings_cache = _default_settings(buy_amt_on=False, buy_amt=0)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 50_000
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_rebuy_block_excludes_from_buyable_codes(self, fresh_state, reset_cash_gate):
        """rebuy_block_on + 금일 매수 종목 → _buyable_codes에서 제외 → execute_buy 호출 안 됨."""
        fresh_state.auto_trade._bought_today = {"005930": 1234567890.0}
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        fresh_state.auto_trade.execute_buy.assert_not_called()

    @pytest.mark.asyncio
    async def test_snapshot_excludes_available_cash_field(self, fresh_state, reset_cash_gate):
        """snapshot에 available_cash 필드가 없는지 확인 — _buyable_codes가 orderable에 의존."""
        # execute_buy 실패 → invalidate_buy_snapshot 호출 안 됨 → snapshot 유지
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_RISE_GUARD))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        # execute_buy 호출은 되었지만 실패 → snapshot 유지
        fresh_state.auto_trade.execute_buy.assert_called_once()
        assert buy_order_executor._last_global_snapshot is not None
        # available_cash 필드가 제거되었는지 확인
        assert "available_cash" not in buy_order_executor._last_global_snapshot


# ── 건별 간격 적용 매수 알고리즘 ──────────────────────────────────────────────

class TestMultiRankBuyAlgorithm:
    """건별 간격 적용 매수 알고리즘 검증 — 1건 매수 성공 후 break, 실패 시 차순위 시도 여부."""

    def _two_targets(self):
        s1 = _stock(code="A001", cur_price=70_000)
        s2 = _stock(code="A002", cur_price=70_000)
        return SectorSummary(
            sectors=[],
            buy_targets=[
                BuyTarget(rank=1, sector_rank=1, stock=s1),
                BuyTarget(rank=2, sector_rank=1, stock=s2),
            ],
            blocked_targets=[],
            version=1,
        )

    def _three_targets(self):
        s1 = _stock(code="A001", cur_price=70_000)
        s2 = _stock(code="A002", cur_price=70_000)
        s3 = _stock(code="A003", cur_price=70_000)
        return SectorSummary(
            sectors=[],
            buy_targets=[
                BuyTarget(rank=1, sector_rank=1, stock=s1),
                BuyTarget(rank=2, sector_rank=1, stock=s2),
                BuyTarget(rank=3, sector_rank=1, stock=s3),
            ],
            blocked_targets=[],
            version=1,
        )

    @pytest.mark.asyncio
    async def test_second_rank_tried_after_first_success_with_remaining_cash(self, fresh_state, reset_cash_gate):
        """1건 매수 성공 후 건별 간격 적용 → 2순위 execute_buy 호출 안 됨 (다음 이벤트 시 간격 판정)."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_loop_breaks_on_cash_zero_after_first_success(self, fresh_state, reset_cash_gate):
        """1건 매수 성공 후 루프 종료 — 잔액 0 여부와 무관하게 건별 간격 적용."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            # 사전 체크=10M, 루프 내 재조회=0
            mock_rm.return_value.get_withdrawable_deposit.side_effect = [10_000_000, 0]
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_loop_breaks_on_max_holding_after_first_success(self, fresh_state, reset_cash_gate):
        """1건 매수 성공 후 루프 종료 — 최대 보유수 도달과 무관하게 건별 간격 적용."""
        fresh_state.integrated_system_settings_cache = _default_settings(max_stock_cnt=1)
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_loop_breaks_on_daily_limit_after_first_success(self, fresh_state, reset_cash_gate):
        """1건 매수 성공 후 루프 종료 — 일일 한도 도달과 무관하게 건별 간격 적용."""
        fresh_state.integrated_system_settings_cache = _default_settings(
            max_daily_total_buy_amt=300_000, max_daily_total_buy_on=True,
        )
        fresh_state.sector_summary_cache = self._two_targets()
        # execute_buy 성공 후 _daily_buy_spent를 한도 이상으로 설정
        async def _set_daily_spent(*args, **kwargs):
            fresh_state.auto_trade._daily_buy_spent = 300_000
            return (True, "")
        fresh_state.auto_trade.execute_buy = AsyncMock(side_effect=_set_daily_spent)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_second_rank_tried_after_first_symbol_block(self, fresh_state, reset_cash_gate):
        """1순위 종목별 차단(등락률) → 2순위 호출됨."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_RISE_GUARD))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 2

    @pytest.mark.asyncio
    async def test_loop_breaks_on_global_block(self, fresh_state, reset_cash_gate):
        """1순위 전체 차단(자동매매 OFF) → 2순위 호출 안 됨."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_AUTO_BUY_OFF))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_risk_loss_rate_reason_blocks_all(self, fresh_state, reset_cash_gate):
        """BUY_REJECT_RISK_LOSS_RATE(일일 손실률 한도) → 전역 차단 → 2순위 호출 안 됨."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_RISK_LOSS_RATE))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_risk_consec_loss_reason_blocks_all(self, fresh_state, reset_cash_gate):
        """BUY_REJECT_RISK_CONSEC_LOSS(연속 손실 한도) → 전역 차단 → 2순위 호출 안 됨."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_RISK_CONSEC_LOSS))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_qty_zero_with_cash_zero_breaks_loop(self, fresh_state, reset_cash_gate):
        """1순위 BUY_REJECT_QTY_ZERO + 잔액 0 → 2순위 호출 안 됨 + _cash_insufficient=True."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_QTY_ZERO))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            # 사전 체크=10M, 루프 내 재조회=0
            mock_rm.return_value.get_withdrawable_deposit.side_effect = [10_000_000, 0]
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1
        assert buy_order_executor._cash_insufficient is True

    @pytest.mark.asyncio
    async def test_qty_zero_with_remaining_cash_continues(self, fresh_state, reset_cash_gate):
        """1순위 BUY_REJECT_QTY_ZERO + 잔액 남음(단가 초과) → 2순위 호출됨."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_QTY_ZERO))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 2

    @pytest.mark.asyncio
    async def test_exception_breaks_loop(self, fresh_state, reset_cash_gate):
        """1순위 예외 → 2순위 호출 안 됨 (안전 종료)."""
        fresh_state.sector_summary_cache = self._two_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(side_effect=Exception("test error"))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1

    @pytest.mark.asyncio
    async def test_loop_breaks_after_two_successes_on_cash_zero(self, fresh_state, reset_cash_gate):
        """1건 매수 성공 후 건별 간격 적용 → 2순위/3순위 호출 안 됨 (잔액과 무관)."""
        fresh_state.sector_summary_cache = self._three_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            # 사전=10M, 1순위 후=10M, 2순위 후=0
            mock_rm.return_value.get_withdrawable_deposit.side_effect = [10_000_000, 10_000_000, 0]
            await evaluate_buy_candidates()
        assert fresh_state.auto_trade.execute_buy.await_count == 1


# ── 차단 사유 bt.reject_reason 기록 (P21 사용자 투명성) ──────────────────────────────

class TestRejectReasonRecording:
    """execute_buy 차단 시 bt.reject_reason에 사유 텍스트 기록 + WS delta 전송 검증."""

    def _two_pass_targets(self):
        s1 = _stock(code="A001", cur_price=70_000)
        s2 = _stock(code="A002", cur_price=70_000)
        return SectorSummary(
            sectors=[],
            buy_targets=[
                BuyTarget(rank=1, sector_rank=1, stock=s1),
                BuyTarget(rank=2, sector_rank=1, stock=s2),
            ],
            blocked_targets=[],
            version=1,
        )

    @pytest.mark.asyncio
    async def test_max_holding_sets_reason_on_all(self, fresh_state, reset_cash_gate):
        """최대 보유종목 초과 → 모든 guard_pass 후보 bt.reject_reason = "최대 보유종목 초과"."""
        fresh_state.integrated_system_settings_cache = _default_settings(max_stock_cnt=1)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[{"qty": 1}, {"qty": 2}]):
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_MAX_HOLDING]
        reset_cash_gate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_buy_amt_zero_sets_reason_on_all(self, fresh_state, reset_cash_gate):
        """종목당 1회 매수금액 0 → 모든 guard_pass 후보 bt.reject_reason = "종목당 1회 매수금액 0"."""
        fresh_state.integrated_system_settings_cache = _default_settings(buy_amt=0)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]):
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_BUY_AMT_ZERO]

    @pytest.mark.asyncio
    async def test_daily_limit_sets_reason_on_all(self, fresh_state, reset_cash_gate):
        """일일 매수한도 초과 → 모든 guard_pass 후보 bt.reject_reason = "일일 매수한도 초과"."""
        fresh_state.integrated_system_settings_cache = _default_settings(
            max_daily_total_buy_on=True, max_daily_total_buy_amt=5_000_000,
        )
        fresh_state.auto_trade._daily_buy_spent = 5_000_000
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]):
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_DAILY_LIMIT]

    @pytest.mark.asyncio
    async def test_cash_zero_sets_reason_on_all(self, fresh_state, reset_cash_gate):
        """예수금 부족 → 모든 guard_pass 후보 bt.reject_reason = "예수금 부족"."""
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm:
            mock_rm.return_value.get_withdrawable_deposit.return_value = 0
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_RISK_CASH]

    @pytest.mark.asyncio
    async def test_per_stock_reject_sets_reason_on_current(self, fresh_state, reset_cash_gate):
        """종목별 차단(상승률 가드) → 해당 종목 bt.reject_reason만 기록, 차순위는 빈 값 유지."""
        fresh_state.sector_summary_cache = self._two_pass_targets()
        # 1순위 종목별 차단, 2순위 성공
        fresh_state.auto_trade.execute_buy = AsyncMock(
            side_effect=[(False, BUY_REJECT_RISE_GUARD), (True, "")]
        )
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        # 1순위(A001)만 차단 사유 기록
        bt1 = ss.buy_targets[0]
        bt2 = ss.buy_targets[1]
        assert bt1.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_RISE_GUARD]
        # 2순위(A002)는 매수 성공 → reject_reason 빈 값 유지
        assert bt2.reject_reason == ""

    @pytest.mark.asyncio
    async def test_global_reject_sets_reason_on_current(self, fresh_state, reset_cash_gate):
        """전체 차단(자동매수 OFF) → 해당 종목 bt.reject_reason 기록 후 루프 종료."""
        fresh_state.sector_summary_cache = self._two_pass_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_AUTO_BUY_OFF))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        bt1 = ss.buy_targets[0]
        assert bt1.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_AUTO_BUY_OFF]
        # notify 호출 확인
        reset_cash_gate.assert_awaited()

    @pytest.mark.asyncio
    async def test_successful_buy_does_not_set_reason(self, fresh_state, reset_cash_gate):
        """매수 성공 → bt.reject_reason 빈 값 유지, notify 호출 안 됨."""
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(True, ""))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        for bt in ss.buy_targets:
            if bt.stock.guard_pass:
                assert bt.reject_reason == ""
        # 매수 성공 시에는 루프 내 notify 호출 없음
        reset_cash_gate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_qty_zero_cash_zero_sets_reason(self, fresh_state, reset_cash_gate):
        """QTY_ZERO + 잔액 0 → 해당 종목 bt.reject_reason = "매수수량 0" 기록 후 루프 종료."""
        fresh_state.sector_summary_cache = self._two_pass_targets()
        fresh_state.auto_trade.execute_buy = AsyncMock(return_value=(False, BUY_REJECT_QTY_ZERO))
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.side_effect = [10_000_000, 0]
            await evaluate_buy_candidates()
        ss = fresh_state.sector_summary_cache
        bt1 = ss.buy_targets[0]
        assert bt1.reject_reason == BUY_REJECT_REASON_TEXT[BUY_REJECT_QTY_ZERO]


# ── 매수 근거 가산점 통합 문자열 생성 (BUY-REASON-S4: P10 SSOT, P20 폴백 금지, P21 사용자 투명성, P23 용어 통일) ──

class TestBuyReasonBoostString:
    """트리거 필드 조합별 가산점 통합 문자열(reason) 생성 + execute_buy 전달 검증.
    표시 순서 고정: 5거래일 고가 → 호가잔량비 → 뉴스 → 프.순.매 (P23 — 매수 후보 화면 라벨과 일치).
    미발생 시 빈 문자열 (P20 폴백 금지).
    """

    @staticmethod
    def _state_with_stock(stock, fresh_state):
        fresh_state.sector_summary_cache = _sector_summary(
            stocks=[stock],
            buy_targets=[BuyTarget(rank=1, sector_rank=1, stock=stock)],
        )
        return fresh_state

    @pytest.mark.asyncio
    async def test_all_boosts_triggered(self, fresh_state, reset_cash_gate):
        """가산점 4개 모두 발생 → 전체 연결 문자열."""
        s = _stock(boost_high_triggered=True, boost_order_ratio_triggered=True,
                   boost_news_triggered=True, boost_program_triggered=True)
        self._state_with_stock(s, fresh_state)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        _kwargs = fresh_state.auto_trade.execute_buy.call_args.kwargs
        assert _kwargs["reason"] == "5거래일 고가 · 호가잔량비 · 📰뉴스 · 프.순.매"

    @pytest.mark.asyncio
    async def test_partial_boosts_triggered(self, fresh_state, reset_cash_gate):
        """5거래일 고가·뉴스만 발생 → 해당 가산점만 연결 (P20 — 미발생 항목 제외)."""
        s = _stock(boost_high_triggered=True, boost_news_triggered=True)
        self._state_with_stock(s, fresh_state)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        _kwargs = fresh_state.auto_trade.execute_buy.call_args.kwargs
        assert _kwargs["reason"] == "5거래일 고가 · 📰뉴스"

    @pytest.mark.asyncio
    async def test_no_boost_triggered_empty_string(self, fresh_state, reset_cash_gate):
        """가산점 미발생 → 빈 문자열 (P20 폴백 금지 — "자동매수" 아님)."""
        s = _stock()  # 모든 트리거 기본값 False
        self._state_with_stock(s, fresh_state)
        with patch("backend.app.services.engine_state.state", fresh_state), \
             patch("backend.app.services.buy_order_executor.auto_buy_effective", return_value=True), \
             patch("backend.app.services.buy_order_executor.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.risk_manager.get_risk_manager") as mock_rm, \
             patch("backend.app.services.daily_time_scheduler.is_order_blocked_by_time", return_value=False):
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            await evaluate_buy_candidates()
        _kwargs = fresh_state.auto_trade.execute_buy.call_args.kwargs
        assert _kwargs["reason"] == ""
