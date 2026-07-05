"""engine_ws.py 단위 테스트 — WS 연결·REG/UNREG 전송·구독 파이프라인 검증.

hang 방지 원칙:
- 실제 asyncio.Lock/Event/wait_for/sleep 사용 금지 → 전부 mock으로 대체
- asyncio.create_task 사용 금지 → 백그라운드 태스크 대신 직접 호출
- state.reg_seq_lock은 MagicMock(__aenter__/__aexit__)으로 대체
- state.reg_ack_event는 MagicMock(wait/clear/set)으로 대체
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import asyncio

import pytest

from backend.app.services.engine_ws import (
    _ws_live,
    _ws_send_reg_unreg_and_wait_ack,
    _ws_send_remove_fire_and_forget,
    _broker_message_handler,
    _handle_ws_data,
    _subscribe_stock_realtime_when_ready,
    _subscribe_account_realtime,
    _log_reg_stock_chunk,
    _subscribe_positions_stocks_realtime,
    _subscribe_radar_stocks_realtime,
    _subscribe_all_tracked_stocks_realtime,
    _subscribe_sector_stocks_0b,
    _ensure_ws_subscriptions_for_positions,
    _run_sector_reg_pipeline,
    _cleanup_stale_ws_subscriptions_on_session_ready,
    _item_cd_is_position,
    _item_cd_tracked_radar_or_ready,
    _sweep_unreg_subscribed_except_positions_and_tracked,
    subscribe_dynamic_data,
    unsubscribe_dynamic_data,
)


def _mock_lock():
    """asyncio.Lock 대체 — 실제 락 없이 즉시 통과하는 mock."""
    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=lock)
    lock.__aexit__ = AsyncMock(return_value=None)
    return lock


def _mock_event():
    """asyncio.Event 대체 — 실제 이벤트 없이 즉시 반환하는 mock."""
    ev = MagicMock()
    ev.wait = AsyncMock()
    ev.clear = MagicMock()
    ev.set = MagicMock()
    return ev


def _mock_state(**overrides):
    """engine_ws.state 기본 mock — 모든 asyncio 객체를 mock으로 대체."""
    mock = MagicMock()
    mock.connector_manager = None
    mock.active_connector = None
    mock.login_ok = False
    mock.reg_seq_lock = _mock_lock()
    mock.reg_ack_event = _mock_event()
    mock.reg_ack_return_code = ""
    mock.REG_POST_ACK_GAP_SEC = 0
    mock.master_stocks_cache = {}
    mock.integrated_system_settings_cache = {}
    mock.ws_reg_pipeline_done = None
    mock.account_rest_bootstrapped = False
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


# ── _ws_live ──────────────────────────────────────────────────────────────────────

class TestWsLive:
    def test_no_connector(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_state.connector_manager = None
            mock_state.active_connector = None
            assert _ws_live() is False

    def test_connector_manager_connected(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_cm = MagicMock()
            mock_cm.is_connected.return_value = True
            mock_state.connector_manager = mock_cm
            mock_state.active_connector = None
            assert _ws_live() is True

    def test_active_connector_connected(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_state.connector_manager = None
            mock_ac = MagicMock()
            mock_ac.is_connected.return_value = True
            mock_state.active_connector = mock_ac
            assert _ws_live() is True

    def test_connector_disconnected(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_cm = MagicMock()
            mock_cm.is_connected.return_value = False
            mock_state.connector_manager = mock_cm
            mock_state.active_connector = None
            assert _ws_live() is False


# ── _ws_send_reg_unreg_and_wait_ack ────────────────────────────────────────────────

class TestWsSendRegUnregAndWaitAck:
    @pytest.mark.asyncio
    async def test_no_sender(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is False
            assert rc == ""

    @pytest.mark.asyncio
    async def test_sender_disconnected(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = False
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_ws.state", mock_state):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is False

    @pytest.mark.asyncio
    async def test_send_failure(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=False)
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_ws.state", mock_state):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is False

    @pytest.mark.asyncio
    async def test_success_with_ack(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=True)
        mock_state = _mock_state(connector_manager=mock_cm)

        async def _fake_wait_for_ok(coro, timeout=None):
            mock_state.reg_ack_return_code = "0"
            if hasattr(coro, "close"):
                coro.close()
            return True

        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_ws.asyncio.wait_for", new=_fake_wait_for_ok):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is True
            assert rc == "0"

    @pytest.mark.asyncio
    async def test_timeout(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=True)
        mock_state = _mock_state(connector_manager=mock_cm)

        async def _fake_wait_for(coro, timeout=None):
            if hasattr(coro, "close"):
                coro.close()
            raise asyncio.TimeoutError()

        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_ws.asyncio.wait_for", new=_fake_wait_for):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is False
            assert rc == ""


# ── _ws_send_remove_fire_and_forget ────────────────────────────────────────────────

class TestWsSendRemoveFireAndForget:
    @pytest.mark.asyncio
    async def test_no_sender(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE"})
            assert result is False

    @pytest.mark.asyncio
    async def test_sender_disconnected(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = False
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_ws.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE"})
            assert result is False

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=True)
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_ws.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE", "grp_no": "4"})
            assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=False)
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_ws.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE", "grp_no": "4"})
            assert result is False


# ── _broker_message_handler ────────────────────────────────────────────────────────

class TestBrokerMessageHandler:
    @pytest.mark.asyncio
    async def test_valid_trnm(self):
        with patch("backend.app.services.engine_ws._handle_ws_data", new_callable=AsyncMock) as mock_handle:
            await _broker_message_handler({"trnm": "REAL", "data": []})
            mock_handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_trnm(self):
        with patch("backend.app.services.engine_ws._handle_ws_data", new_callable=AsyncMock) as mock_handle:
            await _broker_message_handler({"trnm": "UNKNOWN"})
            mock_handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_dict(self):
        with patch("backend.app.services.engine_ws._handle_ws_data", new_callable=AsyncMock) as mock_handle:
            await _broker_message_handler("not_dict")
            mock_handle.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_missing_trnm(self):
        with patch("backend.app.services.engine_ws._handle_ws_data", new_callable=AsyncMock) as mock_handle:
            await _broker_message_handler({})
            mock_handle.assert_not_awaited()


# ── _handle_ws_data ────────────────────────────────────────────────────────────────

class TestHandleWsData:
    @pytest.mark.asyncio
    async def test_delegates_to_dispatch(self):
        with patch("backend.app.services.engine_ws_dispatch.handle_ws_data", new_callable=AsyncMock) as mock_dispatch:
            await _handle_ws_data({"trnm": "LOGIN"})
            mock_dispatch.assert_awaited_once_with({"trnm": "LOGIN"})


# ── _subscribe_stock_realtime_when_ready ────────────────────────────────────────────

class TestSubscribeStockRealtimeWhenReady:
    @pytest.mark.asyncio
    async def test_empty_code(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _subscribe_stock_realtime_when_ready("")

    @pytest.mark.asyncio
    async def test_already_subscribed(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
        mock_state.ws_reg_pipeline_done = None
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _subscribe_stock_realtime_when_ready("005930")

    @pytest.mark.asyncio
    async def test_no_ws_connection(self):
        mock_state = _mock_state()
        mock_state.master_stocks_cache = {"005930": {"_subscribed": False}}
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _subscribe_stock_realtime_when_ready("005930")

    @pytest.mark.asyncio
    async def test_subscribe_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.subscribe_stocks = AsyncMock(return_value=True)
        mock_state = _mock_state(connector_manager=mock_cm)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": False}}
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _subscribe_stock_realtime_when_ready("005930")
            assert mock_state.master_stocks_cache["005930"]["_subscribed"] is True

    @pytest.mark.asyncio
    async def test_subscribe_failure(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.subscribe_stocks = AsyncMock(return_value=False)
        mock_state = _mock_state(connector_manager=mock_cm)
        mock_state.master_stocks_cache = {"005930": {"_subscribed": False}}
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _subscribe_stock_realtime_when_ready("005930")
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]


# ── _subscribe_account_realtime ─────────────────────────────────────────────────────

class TestSubscribeAccountRealtime:
    @pytest.mark.asyncio
    async def test_delegates(self):
        with patch("backend.app.services.engine_ws_reg.subscribe_account_realtime", new_callable=AsyncMock) as mock_fn:
            await _subscribe_account_realtime()
            mock_fn.assert_awaited_once()


# ── _log_reg_stock_chunk ────────────────────────────────────────────────────────────

class TestLogRegStockChunk:
    def test_no_exception(self):
        _log_reg_stock_chunk("batch", 1, 100, 95, 3, 2)


# ── _subscribe_positions_stocks_realtime ────────────────────────────────────────────

class TestSubscribePositionsStocksRealtime:
    @pytest.mark.asyncio
    async def test_delegates(self):
        with patch("backend.app.services.engine_ws_reg.subscribe_positions_stocks_realtime", new_callable=AsyncMock), \
             patch("backend.app.services.engine_ws.state") as mock_state, \
             patch("backend.app.services.ws_subscribe_control._set_status") as mock_set:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
            await _subscribe_positions_stocks_realtime()
            mock_set.assert_called_once_with(quote=True)

    @pytest.mark.asyncio
    async def test_no_subscribed_no_set_status(self):
        with patch("backend.app.services.engine_ws_reg.subscribe_positions_stocks_realtime", new_callable=AsyncMock), \
             patch("backend.app.services.engine_ws.state") as mock_state, \
             patch("backend.app.services.ws_subscribe_control._set_status") as mock_set:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": False}}
            await _subscribe_positions_stocks_realtime()
            mock_set.assert_not_called()


# ── _subscribe_radar_stocks_realtime ────────────────────────────────────────────────

class TestSubscribeRadarStocksRealtime:
    @pytest.mark.asyncio
    async def test_noop(self):
        await _subscribe_radar_stocks_realtime()


# ── _subscribe_all_tracked_stocks_realtime ──────────────────────────────────────────

class TestSubscribeAllTrackedStocksRealtime:
    @pytest.mark.asyncio
    async def test_delegates_both(self):
        with patch("backend.app.services.engine_ws._subscribe_positions_stocks_realtime", new_callable=AsyncMock) as mock_pos, \
             patch("backend.app.services.engine_ws._subscribe_radar_stocks_realtime", new_callable=AsyncMock) as mock_radar:
            await _subscribe_all_tracked_stocks_realtime()
            mock_pos.assert_awaited_once()
            mock_radar.assert_awaited_once()


# ── _subscribe_sector_stocks_0b ─────────────────────────────────────────────────────

class TestSubscribeSectorStocks0b:
    @pytest.mark.asyncio
    async def test_delegates(self):
        with patch("backend.app.services.engine_ws_reg.subscribe_sector_stocks_0b", new_callable=AsyncMock), \
             patch("backend.app.services.ws_subscribe_control._set_status") as mock_set:
            await _subscribe_sector_stocks_0b()
            mock_set.assert_called_once_with(quote=True)


# ── _ensure_ws_subscriptions_for_positions ──────────────────────────────────────────

class TestEnsureWsSubscriptionsForPositions:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _ensure_ws_subscriptions_for_positions()

    @pytest.mark.asyncio
    async def test_not_logged_in(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=False)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_ws._ws_live", return_value=False):
            await _ensure_ws_subscriptions_for_positions()

    @pytest.mark.asyncio
    async def test_real_mode(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=False), \
             patch("backend.app.services.engine_ws._subscribe_account_realtime", new_callable=AsyncMock) as mock_acct, \
             patch("backend.app.services.engine_ws._subscribe_positions_stocks_realtime", new_callable=AsyncMock) as mock_pos, \
             patch("backend.app.services.engine_ws._ws_live", return_value=False):
            await _ensure_ws_subscriptions_for_positions()
            mock_acct.assert_awaited_once()
            mock_pos.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_test_mode_skips_account(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.core.trade_mode.is_test_mode", return_value=True), \
             patch("backend.app.services.engine_ws._subscribe_account_realtime", new_callable=AsyncMock) as mock_acct, \
             patch("backend.app.services.engine_ws._subscribe_positions_stocks_realtime", new_callable=AsyncMock) as mock_pos, \
             patch("backend.app.services.engine_ws._ws_live", return_value=False):
            await _ensure_ws_subscriptions_for_positions()
            mock_acct.assert_not_awaited()
            mock_pos.assert_awaited_once()


# ── _run_sector_reg_pipeline ────────────────────────────────────────────────────────

class TestRunSectorRegPipeline:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _run_sector_reg_pipeline()

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_event = MagicMock()
        mock_event.set = MagicMock()
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True, ws_reg_pipeline_done=mock_event)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.ws_subscribe_control.run_conditional_reg_pipeline", new_callable=AsyncMock) as mock_run, \
             patch("backend.app.services.engine_ws._ws_live", return_value=False):
            await _run_sector_reg_pipeline()
            mock_run.assert_awaited_once()
            mock_event.set.assert_called_once()


# ── _cleanup_stale_ws_subscriptions_on_session_ready ────────────────────────────────

class TestCleanupStaleWsSubscriptions:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state):
            await _cleanup_stale_ws_subscriptions_on_session_ready()

    @pytest.mark.asyncio
    async def test_with_ws(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_cm, account_rest_bootstrapped=False)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.ws_subscribe_control.cleanup_stale_subscriptions", new_callable=AsyncMock) as mock_cleanup:
            await _cleanup_stale_ws_subscriptions_on_session_ready()
            mock_cleanup.assert_awaited_once()


# ── _item_cd_is_position ────────────────────────────────────────────────────────────

class TestItemCdIsPosition:
    def test_match(self):
        assert _item_cd_is_position("005930", {"005930", "000660"}) is True

    def test_no_match(self):
        assert _item_cd_is_position("999999", {"005930"}) is False

    def test_al_suffix_match(self):
        assert _item_cd_is_position("005930", {"005930_AL"}) is True

    def test_empty_pos_keep(self):
        assert _item_cd_is_position("005930", set()) is False


# ── _item_cd_tracked_radar_or_ready ──────────────────────────────────────────────────

class TestItemCdTrackedRadarOrReady:
    def test_subscribed(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
            assert _item_cd_tracked_radar_or_ready("005930") is True

    def test_not_subscribed(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": False}}
            assert _item_cd_tracked_radar_or_ready("005930") is False

    def test_not_in_cache(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_state.master_stocks_cache = {}
            assert _item_cd_tracked_radar_or_ready("999999") is False

    def test_empty_code(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_state.master_stocks_cache = {}
            assert _item_cd_tracked_radar_or_ready("") is False

    def test_zero_code(self):
        with patch("backend.app.services.engine_ws.state") as mock_state:
            mock_state.master_stocks_cache = {}
            assert _item_cd_tracked_radar_or_ready("000000") is False


# ── _sweep_unreg_subscribed_except_positions_and_tracked ────────────────────────────

class TestSweepUnreg:
    @pytest.mark.asyncio
    async def test_noop_returns_zero(self):
        result = await _sweep_unreg_subscribed_except_positions_and_tracked()
        assert result == 0


# ── subscribe_dynamic_data ──────────────────────────────────────────────────────────

class TestSubscribeDynamicData:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_state.state", mock_state):
            await subscribe_dynamic_data(["0D"])

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.subscribe_dynamic = AsyncMock()
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_state.state", mock_state):
            await subscribe_dynamic_data(["0D"])
            mock_cm.subscribe_dynamic.assert_awaited_once_with(["0D"])

    @pytest.mark.asyncio
    async def test_no_subscribe_dynamic_method(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        del mock_cm.subscribe_dynamic
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_state.state", mock_state):
            await subscribe_dynamic_data(["0D"])


# ── unsubscribe_dynamic_data ────────────────────────────────────────────────────────

class TestUnsubscribeDynamicData:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_state.state", mock_state):
            await unsubscribe_dynamic_data(["0D"])

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.unsubscribe_dynamic = AsyncMock()
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_ws.state", mock_state), \
             patch("backend.app.services.engine_state.state", mock_state):
            await unsubscribe_dynamic_data(["0D"])
            mock_cm.unsubscribe_dynamic.assert_awaited_once_with(["0D"])
