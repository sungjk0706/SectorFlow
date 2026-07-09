"""trading.py 단위 테스트 — 매수/매도 실행 분기 및 테스트모드 동등성 검증.

AutoTradeManager의 _to_trade_settings, execute_buy 게이트, 
execute_sell 분기, check_sell_conditions 로직을 검증.
"""
from __future__ import annotations

import pytest
import time as _time
import asyncio
from unittest.mock import AsyncMock, DEFAULT, MagicMock, patch


def _close_coro(*args, **kwargs):
    """mock에 전달된 코루틴을 close하여 RuntimeWarning 방지."""
    for arg in args:
        if asyncio.iscoroutine(arg):
            arg.close()
    return DEFAULT

from backend.app.services.trading import AutoTradeManager


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
        "buy_amt": 1_000_000,
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
    return mgr


# ── _to_trade_settings ─────────────────────────────────────────────────────────

class TestToTradeSettings:
    def test_basic_conversion(self):
        mgr = _make_manager()
        ts = mgr._to_trade_settings(_raw_settings())
        assert ts["max_limit"] == 5
        assert ts["buy_amt"] == 1_000_000
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
            result = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_rebuy_block_today(self):
        mgr = _make_manager()
        mgr._bought_today["005930"] = _time.time()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_rebuy_block_period_hours(self):
        mgr = _make_manager(_raw_settings(rebuy_block_period="2h"))
        mgr._bought_today["005930"] = _time.time()
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_period="2h")
            result = await mgr.execute_buy("005930", 70000, "token")
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
             patch("backend.app.services.engine_strategy_core.check_test_buy_power", return_value=(True, "")), \
             patch("backend.app.services.dry_run.fake_send_order", new_callable=AsyncMock, return_value={"success": True, "order_id": "test1"}), \
             patch("backend.app.services.dry_run.set_stock_name", new_callable=AsyncMock), \
             patch("backend.app.services.dry_run.fake_fill_event", new_callable=AsyncMock), \
             patch("backend.app.services.trade_history.record_buy", new_callable=AsyncMock), \
             patch("backend.app.core.journal.record_order_request", new_callable=AsyncMock), \
             patch("backend.app.services.engine_account._broadcast_buy_limit_status", new_callable=AsyncMock), \
             patch("backend.app.services.trading.asyncio.create_task", side_effect=_close_coro) as mock_create_task, \
             patch("backend.app.services.trading._fire_and_forget_telegram"):
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings(rebuy_block_on=False)
            mock_state.master_stocks_cache = {}
            mock_rm.return_value.circuit_breaker.get_state.return_value = "CLOSED"
            mock_rm.return_value.get_withdrawable_deposit.return_value = 10_000_000
            mock_rm.return_value.check_buy_order_allowed = AsyncMock(return_value=(True, "승인"))
            mock_task = MagicMock()
            mock_task.add_done_callback = MagicMock()
            mock_create_task.return_value = mock_task
            result = await mgr.execute_buy("005930", 70000, "token")
        assert result is True

    @pytest.mark.asyncio
    async def test_has_open_buy_returns_false(self):
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": 0.0, "has_open_buy": True}
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result = await mgr.execute_buy("005930", 70000, "token")
        assert result is False

    @pytest.mark.asyncio
    async def test_throttle_blocks_within_interval(self):
        mgr = _make_manager()
        mgr._buy_state["005930"] = {"last_req_ts": _time.time(), "has_open_buy": False}
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            mock_state.integrated_system_settings_cache = _raw_settings()
            result = await mgr.execute_buy("005930", 70000, "token")
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
            result = await mgr.execute_buy("005930", 0, "token")
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
            result = await mgr.execute_buy("005930", 70000, "token")
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
            result = await mgr.execute_buy("005930", 70000, "token")
        assert result is False


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
            mock_rm.return_value.check_sell_order_allowed.return_value = (True, "승인")
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
            mock_rm.return_value.check_sell_order_allowed.return_value = (True, "승인")
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
            mock_rm.return_value.check_sell_order_allowed.return_value = (True, "승인")
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
            mock_rm.return_value.check_sell_order_allowed.return_value = (True, "승인")
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
            mock_rm.return_value.check_sell_order_allowed.return_value = (True, "승인")
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
            mock_rm.return_value.check_sell_order_allowed.return_value = (True, "승인")
            await mgr.check_sell_conditions([stock], _raw_settings(), "token")
        mgr.execute_sell.assert_not_awaited()


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
