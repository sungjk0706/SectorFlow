"""trading.py 단위 테스트 — 매수/매도 실행 분기 및 테스트모드 동등성 검증.

AutoTradeManager의 _to_trade_settings, execute_buy 게이트, 
execute_sell 분기, check_sell_conditions 로직을 검증.
"""
from __future__ import annotations

import pytest
import time as _time
import asyncio
from unittest.mock import AsyncMock, patch


def _fake_fill_and_set(mgr):
    """fake_fill_event 동기 대기 모의 — 체결 응답 이벤트 설정.

    3단계(가상 체결 동기 대기) 대응: fake_fill_event가 await로 직접 호출되므로,
    모의 객체가 on_fill_update 역할을 대신하여 _fill_event를 설정.
    _fill_event가 None이면 (주문 미전송/guard 차단) 이벤트 설정 생략.
    """
    async def _side(*args, **kwargs):
        if mgr._fill_event is not None:
            mgr._fill_event.set()
    return _side

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
    BUY_REJECT_RISK_MARKET_DATA,
    BUY_REJECT_RISK_MARKET_DROP,
    BUY_REJECT_RISK_SINGLE,
    BUY_REJECT_SIGNAL_INTERVAL,
    BUY_REJECT_ORDER_BUSY,
    BUY_REJECT_FILL_TIMEOUT,
    _map_risk_reason_to_code,
    _broadcast_daily_buy_state_status,
    _broadcast_test_cash_failed,
)


@pytest.fixture(autouse=True)
def _patch_trading_calendar():
    """is_trading_day가 캐시 미로드 RuntimeError를 발생시키지 않도록 mock.
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
        "loss_val": -5.0,
        "ts_apply": False,
        "ts_start_val": 0.0,
        "ts_drop_val": 0.0,
        "broker": "kiwoom",
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
        ts = mgr._to_trade_settings(_raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=-2.0))
        assert ts["chk_ts"] is True
        assert ts["ts_start_val"] == 5.0
        assert ts["ts_drop_val"] == -2.0

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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
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
        """종목당 1회 매수금액 설정값 0 시 사유코드 BUY_REJECT_BUY_AMT_ZERO 반환."""
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

    @pytest.mark.asyncio
    async def test_risk_block_buy_sends_telegram_and_ws_broadcast(self):
        """매수 리스크 차단 시 텔레그램 알림 + risk-block-status WS 브로드캐스트 전송 (P21)."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.dry_run.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.trading._fire_and_forget_telegram") as mock_telegram, \
             patch("backend.app.services.engine_account_notify._safe_broadcast", new=AsyncMock()) as mock_broadcast:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(
                return_value=(False, "일일 손실 한도 초과")
            )
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        assert reason == BUY_REJECT_RISK_LOSS
        # 텔레그램 알림 검증 — 메시지에 종목명·코드·사유 포함 (P21)
        mock_telegram.assert_called_once()
        telegram_msg = mock_telegram.call_args.args[0]
        assert "🛑" in telegram_msg
        assert "삼성전자" in telegram_msg
        assert "005930" in telegram_msg
        assert "일일 손실 한도 초과" in telegram_msg
        # WS 브로드캐스트 검증 — side="buy" (P21, 매도 경로와 동일 패턴 P23)
        mock_broadcast.assert_awaited_once_with("risk-block-status", {
            "blocked": True,
            "side": "buy",
            "reason": "일일 손실 한도 초과",
        })


class TestBroadcastDailyBuyStateStatus:
    """일일 매수 상태 로드 성공/실패 브로드캐스트 검증."""

    @pytest.mark.asyncio
    async def test_failed_broadcasts(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new=AsyncMock()) as mock_bc:
            await _broadcast_daily_buy_state_status(failed=True)
            mock_bc.assert_awaited_once_with("daily-buy-state-status", {"failed": True})

    @pytest.mark.asyncio
    async def test_success_broadcasts(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new=AsyncMock()) as mock_bc:
            await _broadcast_daily_buy_state_status(failed=False)
            mock_bc.assert_awaited_once_with("daily-buy-state-status", {"failed": False})


# ── _broadcast_test_cash_failed 헬퍼 단위 테스트 (P21 사용자 투명성) ──────────

class TestBroadcastTestCashFailed:
    """테스트 예수금 검증 실패 브로드캐스트 검증 (사후 1회성 — 헤더 칩 알림)."""

    @pytest.mark.asyncio
    async def test_failed_broadcasts(self):
        with patch("backend.app.services.engine_account_notify._safe_broadcast", new=AsyncMock()) as mock_bc:
            await _broadcast_test_cash_failed(stk_cd="005930", reason="예수금 부족")
            mock_bc.assert_awaited_once_with("test-cash-failed", {"failed": True, "stk_cd": "005930", "reason": "예수금 부족"})


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

    def test_loss_rate_mapping(self):
        assert _map_risk_reason_to_code("일일 손실률 한도 초과") == BUY_REJECT_RISK_LOSS_RATE

    def test_consec_loss_mapping(self):
        assert _map_risk_reason_to_code("연속 손실 한도 초과 (3회)") == BUY_REJECT_RISK_CONSEC_LOSS

    def test_market_drop_mapping(self):
        assert _map_risk_reason_to_code("KOSPI 급락 (-6.0%)") == BUY_REJECT_RISK_MARKET_DROP

    def test_market_data_mapping(self):
        assert _map_risk_reason_to_code("KOSPI 지수 자료 확인 불가") == BUY_REJECT_RISK_MARKET_DATA

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
        mgr = _make_manager(_raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=-2.0))
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
            await mgr.check_sell_conditions([stock_up], _raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=-2.0), "token")
            # drop_rate = (74000 - 76000) / 76000 * 100 = -2.63% <= -2.0
            await mgr.check_sell_conditions([stock_drop], _raw_settings(ts_apply=True, ts_start_val=5.0, ts_drop_val=-2.0), "token")
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


# ── 매도 리스크 차단 알림 (P21 사용자 투명성) ──────────────────────────────────

class TestSellRiskBlockNotification:
    """매도 리스크 차단 시 텔레그램 알림 + risk-block-status WS 브로드캐스트 검증 (P21)."""

    @pytest.mark.asyncio
    @patch("backend.app.services.trading.auto_sell_effective", return_value=True)
    async def test_risk_block_sell_sends_telegram_and_ws_broadcast(self, _mock_sell):
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
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.trading._fire_and_forget_telegram") as mock_telegram, \
             patch("backend.app.services.engine_account_notify._safe_broadcast", new=AsyncMock()) as mock_broadcast:
            mock_state.realtime_latency_exceeded = False
            mock_rm.return_value.check_sell_order_allowed = AsyncMock(
                return_value=(False, "일일 손실 한도 초과 (매도 차단)")
            )
            await mgr.check_sell_conditions([stock], _raw_settings(), "token")
        # 매도 실행 차단 — execute_sell 호출 없음
        mgr.execute_sell.assert_not_awaited()
        # 텔레그램 알림 검증 — 메시지에 "매도 전체 차단" + 사유 포함 (P21)
        mock_telegram.assert_called_once()
        telegram_msg = mock_telegram.call_args.args[0]
        assert "🛑" in telegram_msg
        assert "매도 전체 차단" in telegram_msg
        assert "일일 손실 한도 초과 (매도 차단)" in telegram_msg
        # WS 브로드캐스트 검증 — side="sell" (기존 동작 유지)
        mock_broadcast.assert_awaited_once_with("risk-block-status", {
            "blocked": True,
            "side": "sell",
            "reason": "일일 손실 한도 초과 (매도 차단)",
        })


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
            "pnl_rate": -6.0, "pnl_amount": -50000,  # 손절 조건 (loss_val -5% 이하 손실)
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
            spent, bought_today = await mgr._load_daily_buy_state()
        expected_total = (700000 + round(700000 * BUY_COMMISSION)) + (600000 + round(600000 * BUY_COMMISSION))
        assert spent == expected_total
        assert set(bought_today.keys()) == {"005930", "000660"}

    @pytest.mark.asyncio
    async def test_load_real_mode_total_amt_excludes_fee(self):
        """실전모드 기록(total_amt=price*qty, fee=0)은 수수료 미포함으로 로드 (현행 유지)."""
        mgr = _make_manager()
        rows = [
            {"stk_cd": "005930", "price": 70000, "qty": 10, "total_amt": 700000, "ts": "2026-07-23T10:00:00"},
        ]
        with patch("backend.app.services.trading.trade_history.get_buy_history", new_callable=AsyncMock, return_value=rows):
            spent, _ = await mgr._load_daily_buy_state()
        assert spent == 700000

    @pytest.mark.asyncio
    async def test_load_empty_rows_returns_zero(self):
        """당일 매수 이력 없으면 spent=0 (None 아님)."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.trade_history.get_buy_history", new_callable=AsyncMock, return_value=[]):
            spent, bought_today = await mgr._load_daily_buy_state()
        assert spent == 0
        assert bought_today == {}

    @pytest.mark.asyncio
    async def test_load_failure_returns_none(self):
        """조회 실패 시 spent=None (매수 차단 모드)."""
        mgr = _make_manager()
        with patch("backend.app.services.trading.trade_history.get_buy_history", new_callable=AsyncMock, side_effect=RuntimeError("db error")):
            spent, bought_today = await mgr._load_daily_buy_state()
        assert spent is None
        assert bought_today == {}

    @pytest.mark.asyncio
    async def test_post_buy_accumulation_test_mode_includes_fee(self):
        """테스트모드 매수 성공 후 _daily_buy_spent가 수수료 포함으로 누적.
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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
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

    @pytest.mark.asyncio
    async def test_post_buy_accumulation_real_mode_excludes_fee(self):
        """실전모드 매수 성공 후 _daily_buy_spent는 수수료 미포함 (P18 부합 — 실전은 증권사 SSOT, 앱 수수료 계산 금지)."""
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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            mock_router.return_value.order.send_order = AsyncMock(return_value={"success": True, "order_id": "real1"})
            # 실전모드: WS "00" 체결 응답 대기 — 테스트에서는 WS 미수신이므로 대기 통과 모의
            mgr._end_fill_await = AsyncMock(return_value=True)
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is True
        # 실전모드: fee=0 → spent = base만
        _expected_base = 14 * 70000
        assert mgr._daily_buy_spent == _expected_base


# ── 종목당 1회 매수금액 단일화 (P10 SSOT, P15 단일 경로, P21 사용자 투명성) ──────
# 누적 한도 로직 제거 검증 — 재매수 차단 OFF 시 같은 종목 buy_amt만큼 반복 매수 허용.

class TestBuyAmtSinglePurchase:
    """buy_amt를 '종목당 1회 매수금액'으로 단일화한 뒤 핵심 동작 검증.
    누적 한도(_symbol_daily_buy_spent) 제거로 재매수 차단 OFF 시 반복 매수가 차단되지 않는지 확인."""

    @pytest.mark.asyncio
    async def test_rebuy_block_disabled_buys_full_buy_amt_each_time(self):
        """재매수 차단 OFF + 같은 종목 2회 매수 → 2회 모두 buy_amt 전체만큼 매수 (누적 한도로 잔여 축소 안 됨).
        핵심 사용자 의도 검증 — 종목당 1회 매수금액 단일화 (P10/P21)."""
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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            # 1차 매수
            result1, _reason1 = await mgr.execute_buy("005930", 70000, "token")
            assert result1 is True
            # 체결 완료 + 연속신호 차단 해제 시뮬레이션 (fake_fill_event가 mock로 실제 실행 안 됨)
            mgr._buy_state["005930"] = {"last_req_ts": 0.0, "has_open_buy": False}
            # 2차 매수 — 누적 한도 없이 buy_amt 전체 재사용
            result2, _reason2 = await mgr.execute_buy("005930", 70000, "token")
            assert result2 is True
        # 2회 모두 buy_amt=1,000,000 기반 14주 매수 → spent = 980,147 * 2
        _expected_base = 14 * 70000
        _expected_fee = round(_expected_base * BUY_COMMISSION)
        _expected_spent = _expected_base + _expected_fee
        assert mgr._daily_buy_spent == _expected_spent * 2

    @pytest.mark.asyncio
    async def test_buy_amt_on_false_no_symbol_spent_reference(self):
        """buy_amt_on=False 분기가 _symbol_daily_buy_spent 참조 없이 동작하는지 검증 (dead code 제거 확인).
        effective_buy_amt=None → 주문가능 금액이 상한 (P16 살아있는 경로)."""
        mgr = _make_manager(_raw_settings(buy_amt_on=False, max_daily_total_buy_on=False))
        # _symbol_daily_buy_spent 인스턴스 변수 완전 제거 확인 (P16 dead code 제거)
        assert not hasattr(mgr, "_symbol_daily_buy_spent")
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", 0)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": True, "order_id": "test1"}), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(buy_amt_on=False, max_daily_total_buy_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is True


# ── execute_buy 매수 근거 전달 (BUY-REASON-S4: P10 SSOT, P15 단일 경로, P16 살아있는 경로, P20 폴백 금지) ──

class TestExecuteBuyReasonPassThrough:
    """execute_buy에 reason 전달 시 record_buy에 그대로 전달되는지 검증.
    P20: reason or "자동매수" 폴밭 제거 — 빈 reason은 빈 문자열 그대로 저장.
    P16: reason이 execute_buy → record_buy까지 단일 배선.
    """

    @pytest.mark.asyncio
    async def test_reason_passed_to_record_buy(self):
        """reason 전달 시 record_buy 호출 인자에 그대로 전달 (P16)."""
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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock) as mock_record_buy, \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.execute_buy(
                "005930", 70000, "token",
                reason="5거래일 고가 · 📰뉴스",
            )
        # record_buy에 reason이 그대로 전달되었는지 검증 (P16)
        _kwargs = mock_record_buy.call_args.kwargs
        assert _kwargs["reason"] == "5거래일 고가 · 📰뉴스"

    @pytest.mark.asyncio
    async def test_empty_reason_no_fallback(self):
        """reason 미전달 시 빈 문자열 그대로 저장 — "자동매수" 폴백 제거 검증 (P20)."""
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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock) as mock_record_buy, \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            await mgr.execute_buy("005930", 70000, "token")  # reason 생략
        _kwargs = mock_record_buy.call_args.kwargs
        # P20: 폴백 금지 — reason은 빈 문자열, "자동매수" 아님
        assert _kwargs["reason"] == ""


# ── execute_buy 주문 전송 실패 (P22 정합성, P15 단일 경로, P18 테스트모드 동등성) ──

class TestExecuteBuyOrderFailure:
    """주문 전송 실패 시 사전 차감 롤백 + 실전 주문 경로 미호출 검증.

    trading.py 422-429: fake_send_order 실패 → release_buy_power(_reserved_cost) 호출.
    현재 이 경로의 테스트 커버리지 0개 — 세션1에서 불변조건 고정.
    """

    @pytest.mark.asyncio
    async def test_buy_order_send_failure_releases_reserved_cash(self):
        """테스트모드 매수 주문 전송 실패 시 release_buy_power 호출 → 주문가능금액 예약 전 복원 (P22).

        시나리오:
          1. reserve_test_buy_power 성공 (사전 차감)
          2. fake_send_order 실패 (success=False)
          3. release_buy_power 호출 → _orderable 예약 전 복원
          4. execute_buy returns (False, BUY_REJECT_ORDER_FAIL)
        """
        from backend.app.services import settlement_engine
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        # 사전 차감될 금액 (reserve_test_buy_power가 반환하는 cost)
        _reserved_cost = 980_147  # 14주 * 70000 + round(14*70000*0.00015)
        # 주문가능금액을 사전 차감 전 잔액으로 설정
        original_cash = 10_000_000
        settlement_engine._orderable = original_cash
        settlement_engine._loaded = True
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=original_cash), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", _reserved_cost)) as mock_reserve, \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": False}) as mock_send, \
             patch("backend.app.services.settlement_engine.release_buy_power", new_callable=AsyncMock) as mock_release, \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = original_cash
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, reason = await mgr.execute_buy("005930", 70000, "token")
        # 주문 실패
        assert result is False
        from backend.app.services.trading import BUY_REJECT_ORDER_FAIL
        assert reason == BUY_REJECT_ORDER_FAIL
        # 사전 차감 호출됨
        mock_reserve.assert_awaited_once()
        # 주문 전송 실패
        mock_send.assert_awaited_once()
        # 롤백 호출 — 사전 차감액이 release_buy_power에 전달됨
        mock_release.assert_awaited_once()
        released_amount = mock_release.call_args.args[0]
        assert released_amount == _reserved_cost, \
            f"롤백 금액이 사전 차감액과 일치해야 함 (P22): expected={_reserved_cost}, actual={released_amount}"

    @pytest.mark.asyncio
    async def test_buy_order_failure_does_not_call_real_broker(self):
        """테스트모드 주문 실패 시 실전 get_router().order.send_order 호출 안 함 (P15/P18).

        테스트모드는 fake_send_order만 사용하고 실전 브로커 경로로 우회하지 않음.
        """
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        _reserved_cost = 980_147
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", _reserved_cost)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": False}), \
             patch("backend.app.services.settlement_engine.release_buy_power", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"), \
             patch("backend.app.services.trading.get_router") as mock_get_router:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, _reason = await mgr.execute_buy("005930", 70000, "token")
        assert result is False
        # 실전 라우터가 조회되지 않아야 함 (테스트모드는 fake_send_order만 사용)
        mock_get_router.assert_not_called()


# ── 주문 직렬화 잠금 시나리오 (결정 1·2·3·6 — 5단계 신규 테스트) ────────────────

class TestOrderSerializationLock:
    """주문 직렬화 잠금 검증 — 매수·매도 공통 잠금으로 동시 주문 차단·교착 방지·타임아웃 알림.

    시나리오:
      1. 잠금 점유 중 매수·매도 주문 요청 시 즉시 차단 (결정 6 — 대기 없이 차단)
      2. 주문 1건 실패 후 잠금 해제 → 다음 주문 정상 진입 (교착 없음 — P25 격리된 실패)
      3. 주문 응답 타임아웃 시 화면 알림 + 잠금 해제 (결정 2·3 — P21 투명성)
    """

    @pytest.mark.asyncio
    async def test_buy_blocked_when_lock_held(self):
        """잠금 점유 중 매수 주문 요청 시 즉시 차단 — BUY_REJECT_ORDER_BUSY 반환 (결정 6)."""
        mgr = _make_manager()
        mgr._order_lock = asyncio.Lock()
        await mgr._order_lock.acquire()  # 다른 주문 실행 중 시뮬레이션
        try:
            result, reason = await mgr.execute_buy("005930", 70000, "token")
            assert result is False
            assert reason == BUY_REJECT_ORDER_BUSY
        finally:
            mgr._order_lock.release()

    @pytest.mark.asyncio
    async def test_sell_blocked_when_lock_held(self):
        """잠금 점유 중 매도 주문 요청 시 즉시 차단 — False 반환 (결정 1·6)."""
        mgr = _make_manager()
        mgr._order_lock = asyncio.Lock()
        await mgr._order_lock.acquire()  # 매수 주문 실행 중 시뮬레이션
        trade_settings = mgr._to_trade_settings(_raw_settings())
        try:
            result = await mgr.execute_sell(
                "005930", 70000, "삼성전자", "손절", 10, -6.0,
                trade_settings, _raw_settings(), "token",
            )
            assert result is False
        finally:
            mgr._order_lock.release()

    @pytest.mark.asyncio
    async def test_buy_failure_releases_lock_for_next_order(self):
        """주문 1건 실패 후 잠금 해제 → 다음 주문 정상 진입 (교착 없음 — P25).

        시나리오:
          1. 첫 번째 execute_buy — 주문 전송 실패 (BUY_REJECT_ORDER_FAIL)
          2. 잠금 해제 확인 (locked() == False)
          3. 두 번째 execute_buy — 잠금 차단(BUY_REJECT_ORDER_BUSY) 아님 → 정상 경로 진입 증명
        """
        from backend.app.services import settlement_engine
        from backend.app.services.trading import BUY_REJECT_ORDER_FAIL
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        _reserved_cost = 980_147
        original_cash = 10_000_000
        settlement_engine._orderable = original_cash
        settlement_engine._loaded = True

        # ── 첫 번째 주문: 실패 ──
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=original_cash), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", _reserved_cost)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": False}), \
             patch("backend.app.services.settlement_engine.release_buy_power", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = original_cash
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result1, reason1 = await mgr.execute_buy("005930", 70000, "token")

        assert result1 is False
        assert reason1 == BUY_REJECT_ORDER_FAIL
        # 잠금 해제 확인 — 교착 상태 아님
        assert mgr._order_lock is not None
        assert mgr._order_lock.locked() is False

        # ── 두 번째 주문: 잠금 차단이 아닌 정상 경로 진입 확인 ──
        with patch("backend.app.services.engine_state.state") as mock_state2, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=original_cash), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm2, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", _reserved_cost)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": False}), \
             patch("backend.app.services.settlement_engine.release_buy_power", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state2.realtime_latency_exceeded = False
            mock_state2.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state2.master_stocks_cache = {}
            mock_rm2.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm2.return_value.get_withdrawable_deposit.return_value = original_cash
            mock_rm2.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result2, reason2 = await mgr.execute_buy("005930", 70000, "token")

        assert result2 is False
        # BUY_REJECT_ORDER_BUSY가 아니면 잠금이 정상 해제되어 정상 진입한 것 (교착 없음)
        # signal_interval 등 다른 게이트에서 차단되어도 잠금 정상 해제 증명은 유효
        assert reason2 != BUY_REJECT_ORDER_BUSY

    @pytest.mark.asyncio
    async def test_fill_timeout_sends_notification_and_releases_lock(self):
        """주문 응답 타임아웃 시 화면 알림 발생 + 잠금 해제 (결정 2·3 — P21 투명성).

        시나리오:
          1. 매수 주문 전송 성공
          2. 체결 응답 타임아웃 (짧은 타임아웃으로 시뮬레이션)
          3. 화면 알림 브로드캐스트 호출 확인
          4. (False, BUY_REJECT_FILL_TIMEOUT) 반환
          5. 잠금 해제 확인 (locked() == False)
        """
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        _reserved_cost = 980_147
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", _reserved_cost)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": True, "order_id": "test1"}), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"), \
             patch.object(mgr, "_fill_timeout_for", return_value=0.01), \
             patch("backend.app.services.trading._broadcast_order_fill_timeout", new_callable=AsyncMock) as mock_broadcast:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, reason = await mgr.execute_buy("005930", 70000, "token")

        assert result is False
        assert reason == BUY_REJECT_FILL_TIMEOUT
        # 화면 알림 브로드캐스트 호출 확인
        mock_broadcast.assert_awaited_once()
        # 잠금 해제 확인 — 타임아웃 후에도 잠금이 풀려 다음 주문 가능
        assert mgr._order_lock is not None
        assert mgr._order_lock.locked() is False


# ── 테스트모드 가상 응답 시간 — 주문 흐름 검증 (4단계 신규 테스트) ──────────────

class TestTestModeFillAwaitFlow:
    """테스트모드 주문 흐름 검증 — "주문 → 대기 → 응답 → 다음" 구조 (P18 동등성).

    3단계에서 가상 체결을 백그라운드 예약에서 주문 흐름 내 동기 대기로 변경.
    본 테스트는 변경된 구조가 올바르게 동작하는지 검증:
      1. fake_fill_event가 await로 직접 호출되는지 (백그라운드 예약이 아님)
      2. 주문 접수(fake_send_order) → 가상 체결 대기(fake_fill_event) → 응답 확인 순서
      3. 가상 응답 시간 대기 후 체결 이벤트가 발생하여 주문이 완료되는지
    """

    @pytest.mark.asyncio
    async def test_fake_fill_event_awaited_not_scheduled(self):
        """가상 체결이 백그라운드 예약이 아닌 await로 직접 호출되는지 검증.

        schedule_engine_task가 호출되지 않고, fake_fill_event가 await로 실행됨을 확인.
        """
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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)) as mock_fill, \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.engine_lifecycle.schedule_engine_task") as mock_schedule, \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, _reason = await mgr.execute_buy("005930", 70000, "token")

        assert result is True
        # fake_fill_event가 await로 호출되었는지 확인 (백그라운드 예약이 아님)
        mock_fill.assert_awaited_once()
        # schedule_engine_task는 호출되지 않아야 함 (백그라운드 예약 제거 확인)
        mock_schedule.assert_not_called()

    @pytest.mark.asyncio
    async def test_order_flow_sequence_send_then_fill_then_await(self):
        """주문 흐름 순서 검증 — 주문 접수 → 가상 체결 대기 → 응답 확인.

        fake_send_order(주문 접수)가 fake_fill_event(가상 체결)보다 먼저 호출되는지,
        그리고 _end_fill_await(응답 확인)가 fake_fill_event 이후에 완료되는지 검증.
        """
        mgr = _make_manager(_raw_settings(rebuy_block_on=False))
        _call_order: list[str] = []

        async def _track_send(*a, **kw):
            _call_order.append("send_order")
            return {"success": True, "order_id": "test1"}

        async def _track_fill(*a, **kw):
            _call_order.append("fill_event")
            if mgr._fill_event is not None:
                mgr._fill_event.set()

        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.trading.auto_buy_effective", return_value=True), \
             patch("backend.app.services.engine_account.get_positions", new_callable=AsyncMock, return_value=[]), \
             patch("backend.app.services.trading.is_test_mode", return_value=True), \
             patch("backend.app.services.settlement_engine.get_available_cash", return_value=10_000_000), \
             patch("backend.app.services.dry_run.estimate_fill_price", return_value=70000), \
             patch("backend.app.services.trading.get_risk_manager") as mock_rm, \
             patch("backend.app.services.data_manager.get_stock_name", return_value="삼성전자"), \
             patch("backend.app.services.engine_strategy_core.reserve_test_buy_power", new_callable=AsyncMock, return_value=(True, "", 490350)), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, side_effect=_track_send), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_track_fill), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, _reason = await mgr.execute_buy("005930", 70000, "token")

        assert result is True
        # 주문 접수가 가상 체결보다 먼저 호출되었는지 확인 ("주문 → 대기 → 응답 → 다음")
        assert _call_order[0] == "send_order", \
            f"주문 접수가 가상 체결보다 먼저 호출되어야 함: {_call_order}"
        assert _call_order[1] == "fill_event", \
            f"가상 체결이 주문 접수 이후에 호출되어야 함: {_call_order}"
        assert len(_call_order) == 2, \
            f"주문 접수 + 가상 체결 2단계만 호출되어야 함: {_call_order}"

    @pytest.mark.asyncio
    async def test_fill_await_completes_after_fake_fill_event(self):
        """가상 응답 시간 대기 후 체결 이벤트 발생으로 응답 대기가 완료되는지 검증.

        fake_fill_event가 _fill_event를 설정하면 _end_fill_await가 타임아웃 없이
        즉시 통과하여 주문이 성공으로 완료되는지 확인.
        """
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
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock, side_effect=_fake_fill_and_set(mgr)), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading._fire_and_forget_telegram"), \
             patch("backend.app.services.trading._broadcast_order_fill_timeout", new_callable=AsyncMock) as mock_timeout:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            result, _reason = await mgr.execute_buy("005930", 70000, "token")

        assert result is True
        # 가상 체결이 응답 이벤트를 설정했으므로 타임아웃 알림이 발생하지 않아야 함
        mock_timeout.assert_not_called()
