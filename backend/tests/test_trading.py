"""trading.py 단위 테스트 — 매수/매도 실행 분기 및 테스트모드 동등성 검증.

AutoTradeManager의 _to_trade_settings, execute_buy 게이트, 
execute_sell 분기, check_sell_conditions 로직을 검증.
"""
from __future__ import annotations

import pytest
import time as _time
import asyncio
from unittest.mock import AsyncMock, DEFAULT, patch


def _close_coro(*args, **kwargs):
    """mock에 전달된 코루틴을 close하여 RuntimeWarning 방지."""
    for arg in args:
        if asyncio.iscoroutine(arg):
            arg.close()
    return DEFAULT

from backend.app.services.trading import AutoTradeManager  # noqa: E402
from backend.app.services.trading import (  # noqa: E402
    BUY_REJECT_AUTO_BUY_OFF,
    BUY_REJECT_BUY_AMT_ZERO,
    BUY_REJECT_DAILY_STATE,
    BUY_REJECT_MAX_HOLDING,
    BUY_REJECT_OPEN_ORDER,
    BUY_REJECT_PRICE_ZERO,
    BUY_REJECT_REALTIME_LATENCY,
    BUY_REJECT_REBUY,
    BUY_REJECT_RISE_GUARD,
    BUY_REJECT_RISK_CASH,
    BUY_REJECT_RISK_CIRCUIT,
    BUY_REJECT_RISK_CONSEC_LOSS,
    BUY_REJECT_RISK_LOSS,
    BUY_REJECT_RISK_LOSS_RATE,
    BUY_REJECT_RISK_PROFIT,
    BUY_REJECT_RISK_PROFIT_RATE,
    BUY_REJECT_RISK_SINGLE,
    BUY_REJECT_SIGNAL_INTERVAL,
    _map_risk_reason_to_code,
)


@pytest.fixture(autouse=True)
def _patch_trading_calendar():
    """is_trading_day가 캐시 미초기화 RuntimeError를 발생시키지 않도록 mock.
    auto_buy_effective / auto_sell_effective가 _master_on → is_trading_day를 호출하기 때문.
    _fire_and_forget_telegram도 mock하여 NotificationWorker 백그라운드 태스크 생성 차단.
    """
    with patch("backend.app.core.trading_calendar.is_trading_day", return_value=True), \
         patch("backend.app.services.engine_state.state") as mock_state, \
         patch("backend.app.services.trading._fire_and_forget_telegram"):
        mock_state.krx_circuit_breaker_active = False
        yield


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _raw_settings(**overrides):
    s = {
        "test_mode_on": True,
        "time_scheduler_on": True,
        "auto_buy_on": True,
        "auto_sell_on": True,
        "buy_time_start": "09:00",
        "buy_time_end": "15:30",
        "sell_time_start": "09:00",
        "sell_time_end": "15:30",
        "max_stock_cnt": 5,
        "max_stock_cnt_on": True,
        "buy_amt": 1_000_000,
        "buy_amt_on": True,
        "max_daily_total_buy_on": False,
        "max_daily_total_buy_amt": 0,
        "rebuy_block_on": True,
        "rebuy_block_period": "today",
        "sell_price_type": "mkt",
        "sell_offset": 0,
        "sell_custom_qty": 0,
        "sell_qty_type": "%",
        "tp_val": 10.0,
        "tp_apply": True,
        "loss_apply": True,
        "loss_val": 5.0,
        "ts_apply": False,
        "ts_start_val": 0.0,
        "ts_drop_val": 0.0,
    }
    s.update(overrides)
    return s


def _make_manager(settings=None):
    mgr = AutoTradeManager(
        get_settings_fn=lambda: settings if settings is not None else _raw_settings(),
    )
    # _ensure_daily_buy_counter가 trade_history.get_buy_history → aiosqlite.connect
    # 백그라운드 스레드를 생성하여 이벤트 루프 종료를 차단하므로 mock로 대체
    mgr._ensure_daily_buy_counter = AsyncMock()
    # _ensure_daily_buy_counter mock가 실제 로드를 수행하지 않으므로
    # _daily_buy_spent를 0으로 설정 (로드 성공 + 당일 매수 없음 상태 시뮬레이션)
    mgr._daily_buy_spent = 0
    return mgr


# ── _to_trade_settings ─────────────────────────────────────────────────────────

class TestToTradeSettings:
    def test_basic_conversion(self):
        mgr = _make_manager()
        ts = mgr._to_trade_settings(_raw_settings())
        assert ts["max_limit"] == 5
        assert ts["max_limit_on"] is True
        assert ts["buy_amt"] == 1_000_000
        assert ts["buy_amt_on"] is True
        assert ts["tp_val"] == 10.0
        assert ts["chk_tp"] is True
        assert ts["chk_loss"] is True
        assert ts["chk_ts"] is False
        assert ts["is_sell_mkt"] is True

    def test_tp_disabled_when_tp_val_zero(self):
        mgr = _make_manager()
        ts = mgr._to_trade_settings(_raw_settings(tp_val=0.0, tp_apply=True))
        assert ts["chk_tp"] is False

    def test_tp_disabled_when_tp_apply_false(self):
        mgr = _make_manager()
        ts = mgr._to_trade_settings(_raw_settings(tp_apply=False))
        assert ts["chk_tp"] is False

    def test_loss_disabled_when_loss_apply_false(self):
        mgr = _make_manager()
        ts = mgr._to_trade_settings(_raw_settings(loss_apply=False))
        assert ts["chk_loss"] is False

    def test_ts_enabled(self):
        mgr = _make_manager()
        ts = mgr._to_trade_settings(_raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=2.0))
        assert ts["chk_ts"] is True
        assert ts["ts_start_val"] == 5.0
        assert ts["ts_drop_val"] == 2.0

    def test_sell_limit_order_type(self):
        mgr = _make_manager()
        ts = mgr._to_trade_settings(_raw_settings(sell_price_type="lmt"))
        assert ts["is_sell_mkt"] is False


# ── execute_buy 게이트 ─────────────────────────────────────────────────────────

class TestExecuteBuyGates:
    @pytest.mark.asyncio
    async def test_auto_disabled_returns_false(self):
        mgr = _make_manager(_raw_settings(time_scheduler_on=False))
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_rebuy_block_today(self):
        mgr = _make_manager()
        mgr._bought_today["005930"] = _time.time()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_rebuy_block_period_hours(self):
        mgr = _make_manager(_raw_settings(rebuy_block_period="2h"))
        mgr._bought_today["005930"] = _time.time()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_period="2h")
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_rebuy_block_disabled(self):
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        mgr._bought_today["005930"] = _time.time()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", 490350)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": True, "order_id": "test1"}), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task", side_effect=_close_coro), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is True

    @pytest.mark.asyncio
    async def test_has_open_buy_returns_false(self):
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": 0.0, "has_open_buy": True}
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_throttle_blocks_within_interval(self):
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": _time.time(), "has_open_buy": False}
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_current_price_zero_returns_false(self):
        mgr = _make_manager()
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, _reason = await mgr.execute_buy("005930", 0, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_buy_amt_zero_returns_false(self):
        mgr = _make_manager(_raw_settings(buy_amt=0))
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(buy_amt=0)
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_max_limit_exceeded_returns_false(self):
        mgr = _make_manager(_raw_settings(max_stock_cnt=1))
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock,
                   return_value=[{"qty": 1}]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[{"qty": 1}]):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(max_stock_cnt=1)
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False


# ── execute_buy 사유코드 검증 (P23 일관성) ──────────────────────────────────────

class TestExecuteBuyReasonCodes:
    """execute_buy 반환값 tuple[bool, str]의 사유코드 검증."""

    @pytest.mark.asyncio
    async def test_auto_buy_off_returns_auto_buy_off_reason(self):
        """자동매매 비활성화 시 사유코드 BUY_REJECT_AUTO_BUY_OFF 반환."""
        mgr = _make_manager(_raw_settings(time_scheduler_on=False))
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_AUTO_BUY_OFF

    @pytest.mark.asyncio
    async def test_rebuy_block_today_returns_rebuy_reason(self):
        """재매수 차단(당일) 시 사유코드 BUY_REJECT_REBUY 반환."""
        mgr = _make_manager()
        mgr._bought_today["005930"] = _time.time()
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_REBUY

    @pytest.mark.asyncio
    async def test_open_order_returns_open_order_reason(self):
        """미체결 주문 존재 시 사유코드 BUY_REJECT_OPEN_ORDER 반환."""
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": 0.0, "has_open_buy": True}
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_OPEN_ORDER

    @pytest.mark.asyncio
    async def test_signal_interval_returns_signal_interval_reason(self):
        """30초 연속신호 차단 시 사유코드 BUY_REJECT_SIGNAL_INTERVAL 반환."""
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": _time.time(), "has_open_buy": False}
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_SIGNAL_INTERVAL

    @pytest.mark.asyncio
    async def test_max_holding_returns_max_holding_reason(self):
        """최대 보유수 초과 시 사유코드 BUY_REJECT_MAX_HOLDING 반환."""
        mgr = _make_manager(_raw_settings(max_stock_cnt=1))
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock,
                   return_value=[{"qty": 1}]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock,
                   return_value=[{"qty": 1}]):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(max_stock_cnt=1)
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_MAX_HOLDING

    @pytest.mark.asyncio
    async def test_buy_amt_zero_returns_buy_amt_zero_reason(self):
        """종목당 한도 설정값 0 시 사유코드 BUY_REJECT_BUY_AMT_ZERO 반환."""
        mgr = _make_manager(_raw_settings(buy_amt=0))
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(buy_amt=0)
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_BUY_AMT_ZERO

    @pytest.mark.asyncio
    async def test_price_zero_returns_price_zero_reason(self):
        """현재가 ≤ 0 시 사유코드 BUY_REJECT_PRICE_ZERO 반환."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result, reason = await mgr.execute_buy("005930", 0, "token")
        assert result is False
        assert reason == BUY_REJECT_PRICE_ZERO

    @pytest.mark.asyncio
    async def test_daily_state_load_fail_returns_daily_state_reason(self):
        """일일 매수 상태 로드 실패 시 사유코드 BUY_REJECT_DAILY_STATE 반환."""
        mgr = _make_manager()
        mgr._daily_buy_spent = None  # 로드 실패 상태 시뮬레이션
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_DAILY_STATE

    @pytest.mark.asyncio
    async def test_realtime_latency_returns_realtime_latency_reason(self):
        """실시간 지연 200ms 초과 시 사유코드 BUY_REJECT_REALTIME_LATENCY 반환."""
        mgr = _make_manager()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = True
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_REALTIME_LATENCY

    @pytest.mark.asyncio
    async def test_rise_guard_returns_rise_guard_reason(self):
        """등락률 상승 가드 시 사유코드 BUY_REJECT_RISE_GUARD 반환."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            mock_state.master_stocks_cache = {"005930": {"change_rate": 8.0}}  # 상승률 8% > 한도 7%
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_RISE_GUARD

    @pytest.mark.asyncio
    async def test_risk_circuit_returns_risk_circuit_reason(self):
        """RiskManager 서킷브레이커 차단 시 사유코드 BUY_REJECT_RISK_CIRCUIT 반환."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(
                return_value=(False, "서킷브레이커 차단 상태 (연속 실패)")
            )
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_RISK_CIRCUIT


# ── _map_risk_reason_to_code 헬퍼 단위 테스트 (P23 일관성) ─────────────────────

class TestMapRiskReasonToCode:
    """RiskManager 사유 문자열 → 사유코드 매핑 검증."""

    def test_circuit_mapping(self):
        assert _map_risk_reason_to_code("서킷브레이커 차단 상태 (연속 실패)") == BUY_REJECT_RISK_CIRCUIT

    def test_loss_mapping(self):
        assert _map_risk_reason_to_code("일일 손실 한도 초과") == BUY_REJECT_RISK_LOSS

    def test_cash_mapping(self):
        assert _map_risk_reason_to_code("예수금 부족") == BUY_REJECT_RISK_CASH

    def test_single_mapping(self):
        assert _map_risk_reason_to_code("단일 종목 비중 한도 초과 (삼성전자)") == BUY_REJECT_RISK_SINGLE

    def test_profit_mapping(self):
        assert _map_risk_reason_to_code("일일 수익 한도 도달") == BUY_REJECT_RISK_PROFIT

    def test_loss_rate_mapping(self):
        assert _map_risk_reason_to_code("일일 손실률 한도 초과") == BUY_REJECT_RISK_LOSS_RATE

    def test_profit_rate_mapping(self):
        assert _map_risk_reason_to_code("일일 수익률 한도 도달") == BUY_REJECT_RISK_PROFIT_RATE

    def test_consec_loss_mapping(self):
        assert _map_risk_reason_to_code("연속 손실 한도 초과 (3회)") == BUY_REJECT_RISK_CONSEC_LOSS

    def test_unknown_falls_back_to_circuit(self):
        """알 수 없는 사유는 보수적 전체 차단(BUY_REJECT_RISK_CIRCUIT) 분류 (P20 폴백 금지)."""
        assert _map_risk_reason_to_code("알 수 없는 리스크 사유") == BUY_REJECT_RISK_CIRCUIT


# ── check_sell_conditions ──────────────────────────────────────────────────────

class TestCheckSellConditions:
    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_sell_auto_disabled_returns_early(self, _mock_sell):
        mgr = _make_manager(_raw_settings(time_scheduler_on=False))
        result = await mgr.check_sell_conditions([], _raw_settings(time_scheduler_on=False), "token")
        # Should not raise, should return None
        assert result is None

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_stop_loss_trigger(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_price": "65000",
            "qty": "10",
            "pnl_rate": -6.0,
            "pnl_amount": -50000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions([stock], _raw_settings(), "token")
        mgr.execute_sell.assert_awaited_once()
        call_kwargs = mgr.execute_sell.call_args
        assert "손절" in call_kwargs.args[3]

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_take_profit_trigger(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_price": "77000",
            "qty": "10",
            "pnl_rate": 11.0,
            "pnl_amount": 70000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions([stock], _raw_settings(), "token")
        mgr.execute_sell.assert_awaited_once()
        call_kwargs = mgr.execute_sell.call_args
        assert "익절" in call_kwargs.args[3]

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_no_trigger_when_conditions_not_met(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_price": "71000",
            "qty": "10",
            "pnl_rate": 1.0,
            "pnl_amount": 10000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions([stock], _raw_settings(), "token")
        mgr.execute_sell.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_trailing_stop_trigger(self, _mock_sell):
        mgr = _make_manager(_raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=2.0))
        mgr.execute_sell = AsyncMock()
        # First call: pnl_rate=8% → sets highest_price
        stock_up = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_price": "76000",
            "qty": "10",
            "pnl_rate": 8.0,
            "pnl_amount": 60000,
        }
        stock_drop = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_price": "74000",
            "qty": "10",
            "pnl_rate": 5.7,
            "pnl_amount": 40000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions([stock_up], _raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=2.0), "token")
            # drop_rate = (76000 - 74000) / 76000 * 100 = 2.63% >= 2.0
            await mgr.check_sell_conditions([stock_drop], _raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=2.0), "token")
        # First call: no sell (trailing stop not triggered yet, just tracking high)
        # Second call: trailing stop triggered
        assert mgr.execute_sell.await_count == 1

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_recent_sell_blocks_reorder(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        mgr._recent_sells.add("005930")
        stock = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_price": "65000",
            "qty": "10",
            "pnl_rate": -6.0,
            "pnl_amount": -50000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions([stock], _raw_settings(), "token")
        mgr.execute_sell.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_zero_qty_skipped(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930",
            "stk_nm": "삼성전자",
            "cur_price": "65000",
            "qty": "0",
            "pnl_rate": -6.0,
            "pnl_amount": 0,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions([stock], _raw_settings(), "token")
        mgr.execute_sell.assert_not_awaited()


# ── 매도 주문 간격 게이트 ──────────────────────────────────────────────────────

class TestSellIntervalGate:
    """check_sell_conditions 진입 전 매도 간격 게이트 (trading.py:611-613).

    손절 포함 모든 매도에 간격이 적용됨 (사용자 결정 — plan_order_interval.md 1-3).
    """

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_sell_interval_blocks_within_period(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930", "stk_nm": "삼성전자",
            "cur_price": "65000", "qty": "10",
            "pnl_rate": -6.0, "pnl_amount": -50000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_state._last_global_sell_ts = _time.time()  # 간격 내
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions(
                [stock], _raw_settings(sell_interval_on=True, sell_interval_sec=30), "token",
            )
        mgr.execute_sell.assert_not_awaited()

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_sell_interval_passes_after_period(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930", "stk_nm": "삼성전자",
            "cur_price": "65000", "qty": "10",
            "pnl_rate": -6.0, "pnl_amount": -50000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_state._last_global_sell_ts = _time.time() - 60  # 간격(30초) 초과
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions(
                [stock], _raw_settings(sell_interval_on=True, sell_interval_sec=30), "token",
            )
        mgr.execute_sell.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_sell_interval_off_passes(self, _mock_sell):
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930", "stk_nm": "삼성전자",
            "cur_price": "65000", "qty": "10",
            "pnl_rate": -6.0, "pnl_amount": -50000,
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_state._last_global_sell_ts = _time.time()  # 간격 내라도 토글 OFF면 통과
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions(
                [stock], _raw_settings(sell_interval_on=False, sell_interval_sec=30), "token",
            )
        mgr.execute_sell.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_sell_interval_applies_to_loss_cut(self, _mock_sell):
        """손절 조건 충족 종목도 간격 내면 매도 차단 — 손절 포함 모든 매도에 적용 (사용자 결정)."""
        mgr = _make_manager()
        mgr.execute_sell = AsyncMock()
        stock = {
            "stk_cd": "005930", "stk_nm": "삼성전자",
            "cur_price": "65000", "qty": "10",
            "pnl_rate": -6.0, "pnl_amount": -50000,  # 손절 조건 (loss_val 5% 초과 손실)
        }
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm:
            mock_state.realtime_latency_exceeded = False
            mock_state._last_global_sell_ts = _time.time()  # 간격 내
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.check_sell_conditions(
                [stock], _raw_settings(sell_interval_on=True, sell_interval_sec=30), "token",
            )
        mgr.execute_sell.assert_not_awaited()  # 손절이어도 간격 게이트가 차단

    @pytest.mark.asyncio
    async def test_mark_order_executed_updates_sell_ts(self):
        """mark_order_executed("sell") 호출 시 _last_global_sell_ts 갱신 (trading.py:535-536 배선)."""
        from backend.app.services.order_interval import mark_order_executed
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state._last_global_sell_ts = 0.0
            mark_order_executed("sell")
            assert mock_state._last_global_sell_ts > 0


# ── on_fill_update ─────────────────────────────────────────────────────────────

class TestOnFillUpdate:
    @pytest.mark.asyncio
    async def test_buy_fill_clears_open_buy(self):
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": 0.0, "has_open_buy": True}
        with patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"):
            await mgr.on_fill_update("005930", "1", 0, "token")
        assert mgr._buy_state["005930"]["has_open_buy"] is False

    @pytest.mark.asyncio
    async def test_sell_fill_clears_recent_sell(self):
        mgr = _make_manager()
        mgr._recent_sells.add("005930")
        with patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"):
            await mgr.on_fill_update("005930", "2", 0, "token")
        assert "005930" not in mgr._recent_sells

    @pytest.mark.asyncio
    async def test_cancel_clears_open_buy(self):
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": 0.0, "has_open_buy": True}
        await mgr.on_fill_update("005930", "3", 0, "token")
        assert mgr._buy_state["005930"]["has_open_buy"] is False

    @pytest.mark.asyncio
    async def test_buy_fill_nonzero_unex_keeps_open_buy(self):
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": 0.0, "has_open_buy": True}
        await mgr.on_fill_update("005930", "1", 5, "token")
        assert mgr._buy_state["005930"]["has_open_buy"] is True


# ── 일일/종목당 매수 한도 수수료 포함 누적 (P22 정합성, P10 SSOT) ──────────────
class TestDailyBuySpentFeeInclusive:
    """_load_daily_buy_state와 매수 후 누적이 trade_history.total_amt 기준
    (테스트모드: 수수료 포함 / 실전모드: 순수 매수가)으로 일치하는지 검증."""

    @pytest.mark.asyncio
    async def test_load_uses_total_amt_sum(self):
        """_load_daily_buy_state가 price*qty가 아닌 total_amt 합으로 로드."""
        from backend.app.core.constants import BUY_COMMISSION
        mgr = _make_manager()
        # trade_history 기록: 테스트모드 fee 포함 total_amt
        rows = [
            {"stk_cd": "005930", "price": 70000, "qty": 10, "total_amt": 700000 + round(700000 * BUY_COMMISSION), "ts": "2026-07-23T10:00:00"},
            {"stk_cd": "000660", "price": 120000, "qty": 5, "total_amt": 600000 + round(600000 * BUY_COMMISSION), "ts": "2026-07-23T10:30:00"},
        ]
        with patch("backend.app.services.trading.trade_history.get_buy_history", new_callable=AsyncMock, return_value=rows):
            spent, bought_today, symbol_spent = await mgr._load_daily_buy_state()
        expected_total = (700000 + round(700000 * BUY_COMMISSION)) + (600000 + round(600000 * BUY_COMMISSION))
        assert spent == expected_total
        assert symbol_spent["005930"] == 700000 + round(700000 * BUY_COMMISSION)
        assert symbol_spent["000660"] == 600000 + round(600000 * BUY_COMMISSION)
        assert set(bought_today.keys()) == {"005930", "000660"}

    @pytest.mark.asyncio
    async def test_load_real_mode_total_amt_excludes_fee(self):
        """실전모드 기록(total_amt=price*qty, fee=0)은 수수료 미포함으로 로드 (현행 유지)."""
        mgr = _make_manager()
        rows = [
            {"stk_cd": "005930", "price": 70000, "qty": 10, "total_amt": 700000, "ts": "2026-07-23T10:00:00"},
        ]
        with patch("backend.app.services.trading.trade_history.get_buy_history", new_callable=AsyncMock, return_value=rows):
            spent, _, symbol_spent = await mgr._load_daily_buy_state()
        assert spent == 700000
        assert symbol_spent["005930"] == 700000

    @pytest.mark.asyncio
    async def test_load_empty_rows_returns_zero(self):
        """당일 매수 이력 없으면 spent=0 (None 아님)."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[]):
            spent, bought_today, symbol_spent = await mgr._load_daily_buy_state()
        assert spent == 0
        assert bought_today == {}
        assert symbol_spent == {}

    @pytest.mark.asyncio
    async def test_load_failure_returns_none(self):
        """조회 실패 시 spent=None (매수 차단 모드)."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.trade_history.get_buy_history", new_callable=AsyncMock, side_effect=RuntimeError("db error")):
            spent, bought_today, symbol_spent = await mgr._load_daily_buy_state()
        assert spent is None
        assert bought_today == {}
        assert symbol_spent == {}

    @pytest.mark.asyncio
    async def test_post_buy_accumulation_test_mode_includes_fee(self):
        """테스트모드 매수 성공 후 _daily_buy_spent/_symbol_daily_buy_spent가 수수료 포함으로 누적.
        trade_history.record_buy의 total_amt 공식(base + round(base*BUY_COMMISSION))과 동일 (P10/P22)."""
        from backend.app.core.constants import BUY_COMMISSION
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", 490350)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": True, "order_id": "test1"}), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task", side_effect=_close_coro), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is True
        # buy_qty = max_buy_qty_for_budget(70000, 1_000_000, is_test=True)
        #   = 14 (cost 980_000 + round(980_000*0.00015)=147 → 980_147 ≤ 1_000_000)
        # base = 14 * 70000 = 980_000
        # fee = round(980_000 * 0.00015) = 147
        # spent = 980_147
        _expected_base = 14 * 70000
        _expected_fee = round(_expected_base * BUY_COMMISSION)
        _expected_spent = _expected_base + _expected_fee
        assert mgr._daily_buy_spent == _expected_spent
        assert mgr._symbol_daily_buy_spent["005930"] == _expected_spent

    @pytest.mark.asyncio
    async def test_post_buy_accumulation_real_mode_excludes_fee(self):
        """실전모드 매수 성공 후 _daily_buy_spent는 수수료 미포함 (현행 유지, P18 갭은 HANDOVER 기록)."""
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=False), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", 0)), \
             patch("backend.app.services.trading.get_router") as mock_router, \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task", side_effect=_close_coro), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            mock_router.return_value.order.send_order = AsyncMock(return_value={"success": True, "order_id": "real1"})
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is True
        # 실전모드: fee=0 → spent = base만
        _expected_base = 14 * 70000
        assert mgr._daily_buy_spent == _expected_base
        assert mgr._symbol_daily_buy_spent["005930"] == _expected_base
