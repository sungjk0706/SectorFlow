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
    _subscribe_account_realtime,
    _subscribe_positions_stocks_realtime,
    _ensure_ws_subscriptions_for_positions,
    _run_sector_reg_pipeline,
    _cleanup_stale_ws_subscriptions_on_session_ready,
    subscribe_dynamic_data,
    unsubscribe_dynamic_data,
)
from backend.app.services.engine_ws_reg import subscribe_sector_stocks_0b as subscribe_sector_stocks_0b_impl


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
    """engine_state.state 기본 mock — 모든 asyncio 객체를 mock으로 대체."""
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
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.connector_manager = None
            mock_state.active_connector = None
            assert _ws_live() is False

    def test_connector_manager_connected(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_cm = MagicMock()
            mock_cm.is_connected.return_value = True
            mock_state.connector_manager = mock_cm
            mock_state.active_connector = None
            assert _ws_live() is True

    def test_active_connector_connected(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.connector_manager = None
            mock_ac = MagicMock()
            mock_ac.is_connected.return_value = True
            mock_state.active_connector = mock_ac
            assert _ws_live() is True

    def test_connector_disconnected(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
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
        with patch("backend.app.services.engine_state.state", mock_state):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is False
            assert rc == ""

    @pytest.mark.asyncio
    async def test_sender_disconnected(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = False
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_state.state", mock_state):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is False

    @pytest.mark.asyncio
    async def test_send_failure(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=False)
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_state.state", mock_state):
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

        with patch("backend.app.services.engine_state.state", mock_state), \
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

        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_ws.asyncio.wait_for", new=_fake_wait_for):
            ok, rc = await _ws_send_reg_unreg_and_wait_ack({"trnm": "REG"})
            assert ok is False
            assert rc == ""


# ── _ws_send_remove_fire_and_forget ────────────────────────────────────────────────

class TestWsSendRemoveFireAndForget:
    @pytest.mark.asyncio
    async def test_no_sender(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE"})
            assert result is False

    @pytest.mark.asyncio
    async def test_sender_disconnected(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = False
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE"})
            assert result is False

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=True)
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE", "grp_no": "4"})
            assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.send_message = AsyncMock(return_value=False)
        mock_state = _mock_state(connector_manager=mock_cm)
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await _ws_send_remove_fire_and_forget({"trnm": "REMOVE", "grp_no": "4"})
            assert result is False


# ── _broker_message_handler ────────────────────────────────────────────────────────

class TestBrokerMessageHandler:
    @pytest.mark.asyncio
    async def test_valid_trnm(self):
        with patch("backend.app.services.engine_ws._handle_ws_data", new_callable=AsyncMock) as mock_handle:
            await _broker_message_handler({"trnm": "LOGIN", "return_code": "0"})
            mock_handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_real_not_forwarded(self):
        with patch("backend.app.services.engine_ws._handle_ws_data", new_callable=AsyncMock) as mock_handle:
            await _broker_message_handler({"trnm": "REAL", "data": []})
            mock_handle.assert_not_awaited()

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


# ── _subscribe_account_realtime ─────────────────────────────────────────────────────

class TestSubscribeAccountRealtime:
    @pytest.mark.asyncio
    async def test_delegates(self):
        with patch("backend.app.services.engine_ws_reg.subscribe_account_realtime", new_callable=AsyncMock) as mock_fn:
            await _subscribe_account_realtime()
            mock_fn.assert_awaited_once()


# ── _subscribe_positions_stocks_realtime ────────────────────────────────────────────

class TestSubscribePositionsStocksRealtime:
    @pytest.mark.asyncio
    async def test_delegates(self):
        with patch("backend.app.services.engine_ws_reg.subscribe_positions_stocks_realtime", new_callable=AsyncMock), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.ws_subscribe_control._set_status") as mock_set:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
            await _subscribe_positions_stocks_realtime()
            mock_set.assert_called_once_with(quote=True)

    @pytest.mark.asyncio
    async def test_no_subscribed_no_set_status(self):
        with patch("backend.app.services.engine_ws_reg.subscribe_positions_stocks_realtime", new_callable=AsyncMock), \
             patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.ws_subscribe_control._set_status") as mock_set:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": False}}
            await _subscribe_positions_stocks_realtime()
            mock_set.assert_not_called()


# ── subscribe_sector_stocks_0b 한도 적용 로직 (engine_ws_reg 직접 검증) ──────────────

class TestSubscribeSectorStocks0bLimit:
    """subscribe_sector_stocks_0b 내 한도 적용 로직 검증 (신규 — 설정 키 이관)."""

    @pytest.mark.asyncio
    async def test_respects_configured_limit(self):
        """설정된 한도값이 반영되는지 검증 — 보유 10 + 필터 100, 한도 50 → 필터 40만 등록."""
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.subscribe_stocks = AsyncMock(return_value=True)
        # 보유 10개 + 필터 통과 100개 (보유와 미중복)
        pos_positions = [{"stk_cd": f"00000{i+1}", "qty": 1} for i in range(10)]
        master_cache: dict = {}
        for i in range(10):
            master_cache[f"00000{i+1}"] = {"_filtered": False}
        for i in range(100):
            master_cache[f"0001{i:03d}"] = {"_filtered": True}
        mock_state = _mock_state(
            connector_manager=mock_cm,
            login_ok=True,
            master_stocks_cache=master_cache,
            integrated_system_settings_cache={"subscribe.max_0b_count": 50},
        )
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=pos_positions)):
            await subscribe_sector_stocks_0b_impl()
        # subscribe_stocks 호출: 1) 보유 10개, 2) 필터 40개 (한도 50 - 보유 10)
        assert mock_cm.subscribe_stocks.await_count == 2
        pos_call_args = mock_cm.subscribe_stocks.await_args_list[0].args[0]
        filter_call_args = mock_cm.subscribe_stocks.await_args_list[1].args[0]
        assert len(pos_call_args) == 10
        assert len(filter_call_args) == 40

    @pytest.mark.asyncio
    async def test_defaults_to_200_when_key_missing(self):
        """설정 키 없을 때 기본값 200 적용 검증 (P22 호환성) — 보유 10 + 필터 300, 한도 200 → 필터 190."""
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.subscribe_stocks = AsyncMock(return_value=True)
        pos_positions = [{"stk_cd": f"00000{i+1}", "qty": 1} for i in range(10)]
        master_cache: dict = {}
        for i in range(10):
            master_cache[f"00000{i+1}"] = {"_filtered": False}
        for i in range(300):
            master_cache[f"0001{i:03d}"] = {"_filtered": True}
        mock_state = _mock_state(
            connector_manager=mock_cm,
            login_ok=True,
            master_stocks_cache=master_cache,
            integrated_system_settings_cache={},
        )
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_account.get_positions", new=AsyncMock(return_value=pos_positions)):
            await subscribe_sector_stocks_0b_impl()
        assert mock_cm.subscribe_stocks.await_count == 2
        pos_call_args = mock_cm.subscribe_stocks.await_args_list[0].args[0]
        filter_call_args = mock_cm.subscribe_stocks.await_args_list[1].args[0]
        assert len(pos_call_args) == 10
        assert len(filter_call_args) == 190  # 200 - 10


# ── _ensure_ws_subscriptions_for_positions ──────────────────────────────────────────

class TestEnsureWsSubscriptionsForPositions:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_state.state", mock_state):
            await _ensure_ws_subscriptions_for_positions()

    @pytest.mark.asyncio
    async def test_not_logged_in(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=False)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.engine_ws._ws_live", return_value=False):
            await _ensure_ws_subscriptions_for_positions()

    @pytest.mark.asyncio
    async def test_real_mode(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state):
            await _run_sector_reg_pipeline()

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_event = MagicMock()
        mock_event.set = MagicMock()
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True, ws_reg_pipeline_done=mock_event)
        with patch("backend.app.services.engine_state.state", mock_state), \
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
        with patch("backend.app.services.engine_state.state", mock_state):
            await _cleanup_stale_ws_subscriptions_on_session_ready()

    @pytest.mark.asyncio
    async def test_with_ws(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_state = _mock_state(connector_manager=mock_cm, account_rest_bootstrapped=False)
        with patch("backend.app.services.engine_state.state", mock_state), \
             patch("backend.app.services.ws_subscribe_control.cleanup_stale_subscriptions", new_callable=AsyncMock) as mock_cleanup:
            await _cleanup_stale_ws_subscriptions_on_session_ready()
            mock_cleanup.assert_awaited_once()


# ── subscribe_dynamic_data ──────────────────────────────────────────────────────────

class TestSubscribeDynamicData:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_state.state", mock_state):
            await subscribe_dynamic_data(["0D"])

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.subscribe_dynamic = AsyncMock()
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_state.state", mock_state):
            await subscribe_dynamic_data(["0D"])
            mock_cm.subscribe_dynamic.assert_awaited_once_with(["0D"])

    @pytest.mark.asyncio
    async def test_no_subscribe_dynamic_method(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        del mock_cm.subscribe_dynamic
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_state.state", mock_state):
            await subscribe_dynamic_data(["0D"])


# ── unsubscribe_dynamic_data ────────────────────────────────────────────────────────

class TestUnsubscribeDynamicData:
    @pytest.mark.asyncio
    async def test_no_ws(self):
        mock_state = _mock_state()
        with patch("backend.app.services.engine_state.state", mock_state):
            await unsubscribe_dynamic_data(["0D"])

    @pytest.mark.asyncio
    async def test_success(self):
        mock_cm = MagicMock()
        mock_cm.is_connected.return_value = True
        mock_cm.unsubscribe_dynamic = AsyncMock()
        mock_state = _mock_state(connector_manager=mock_cm, login_ok=True)
        with patch("backend.app.services.engine_state.state", mock_state):
            await unsubscribe_dynamic_data(["0D"])
            mock_cm.unsubscribe_dynamic.assert_awaited_once_with(["0D"])
