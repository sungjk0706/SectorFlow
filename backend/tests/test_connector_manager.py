"""connector_manager.py 단위 테스트 — 다중 증권사 WS Connector 관리자 검증.

ConnectorManager: __init__/_build, _create_single, 콜백 설정, connect_all/disconnect_all,
_on_reconnect_success, 상태 조회, send_message, subscribe/unsubscribe 라우팅

의존성: state (lazy import), CONNECTOR_REGISTRY (lazy loading), asyncio.gather, engine_ws_reg
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _mock_state(broker="kiwoom", websocket=None):
    """engine_state.state mock — broker_config 포함."""
    mock = MagicMock()
    mock.integrated_system_settings_cache = {
        "broker": broker,
        "broker_config": {"websocket": websocket or broker},
    }
    return mock


def _mock_connector(connected=True, **overrides):
    """BrokerConnector mock 생성."""
    conn = MagicMock()
    conn.is_connected = MagicMock(return_value=connected)
    conn.connect = AsyncMock(return_value=None)
    conn.disconnect = AsyncMock(return_value=None)
    conn.set_message_callback = MagicMock()
    conn.set_reconnect_success_callback = MagicMock()
    conn.send_message = AsyncMock(return_value=True)
    conn.subscribe_stocks = AsyncMock(return_value=True)
    conn.unsubscribe_stocks = AsyncMock(return_value=True)
    conn.subscribe_account = AsyncMock(return_value=True)
    conn.subscribe_index = AsyncMock(return_value=True)
    conn.supports_ack = MagicMock(return_value=True)
    conn.unsubscribe_all = AsyncMock(return_value=True)
    conn.subscribe_dynamic = AsyncMock(return_value=None)
    conn.unsubscribe_dynamic = AsyncMock(return_value=None)
    for k, v in overrides.items():
        setattr(conn, k, v)
    return conn


def _make_manager_with_connectors(connectors_dict):
    """ConnectorManager 인스턴스를 _build를 우회하여 생성."""
    with patch("backend.app.services.engine_state.state", _mock_state()):
        from backend.app.core.connector_manager import ConnectorManager
        mgr = ConnectorManager.__new__(ConnectorManager)
        mgr._connectors = connectors_dict
        mgr._callback = None
        mgr._sub_codes = {}
        return mgr


# ── __init__ / _build ──────────────────────────────────────────────────────────

class TestInitBuild:
    def test_init_creates_connectors_from_broker_config(self):
        mock_conn = _mock_connector()
        with (
            patch("backend.app.services.engine_state.state", _mock_state(broker="kiwoom")),
            patch("backend.app.core.connector_manager.ConnectorManager._create_single", staticmethod(lambda name: mock_conn)),
        ):
            from backend.app.core.connector_manager import ConnectorManager
            mgr = ConnectorManager()
            assert "kiwoom" in mgr._connectors
            assert mgr._connectors["kiwoom"] is mock_conn

    def test_init_multiple_brokers(self):
        conn1 = _mock_connector()
        conn2 = _mock_connector()
        connectors = {"kiwoom": conn1, "ls": conn2}

        def fake_create(name):
            return connectors[name]

        with (
            patch("backend.app.services.engine_state.state", _mock_state(broker="kiwoom,ls")),
            patch("backend.app.core.connector_manager.ConnectorManager._create_single", staticmethod(fake_create)),
        ):
            from backend.app.core.connector_manager import ConnectorManager
            mgr = ConnectorManager()
            assert len(mgr._connectors) == 2
            assert "kiwoom" in mgr._connectors
            assert "ls" in mgr._connectors

    def test_init_skips_unknown_broker(self):
        mock_conn = _mock_connector()

        def fake_create(name):
            if name == "unknown":
                raise ValueError("지원하지 않는 증권사: unknown")
            return mock_conn

        with (
            patch("backend.app.services.engine_state.state", _mock_state(broker="kiwoom,unknown")),
            patch("backend.app.core.connector_manager.ConnectorManager._create_single", staticmethod(fake_create)),
        ):
            from backend.app.core.connector_manager import ConnectorManager
            mgr = ConnectorManager()
            assert "kiwoom" in mgr._connectors
            assert "unknown" not in mgr._connectors

    def test_init_empty_brokers(self):
        with patch("backend.app.services.engine_state.state", _mock_state(broker="")):
            from backend.app.core.connector_manager import ConnectorManager
            mgr = ConnectorManager()
            assert len(mgr._connectors) == 0

    def test_init_raises_when_websocket_missing(self):
        """broker_config.websocket이 없으면 정규화 누락 오류 — 폴백 대신 명시적 실패 (P20).

        app.py 시작 시 build_engine_settings_dict로 정규화되므로,
        websocket 키가 없으면 설정 파이프라인 오류를 의미함.
        """
        mock_conn = _mock_connector()
        state = MagicMock()
        state.integrated_system_settings_cache = {
            "broker": "kiwoom",
            "broker_config": {},  # websocket 키 없음 — 정규화 누락 시뮬레이션
        }
        with (
            patch("backend.app.services.engine_state.state", state),
            patch("backend.app.core.connector_manager.ConnectorManager._create_single", staticmethod(lambda name: mock_conn)),
            pytest.raises(KeyError),
        ):
            from backend.app.core.connector_manager import ConnectorManager
            ConnectorManager()


# ── _create_single ─────────────────────────────────────────────────────────────

class TestCreateSingle:
    def test_create_single_success(self):
        mock_conn = _mock_connector()
        mock_registry = {"kiwoom": {"create_connector": lambda: mock_conn}}
        with patch("backend.app.core.broker_registry.CONNECTOR_REGISTRY", mock_registry):
            from backend.app.core.connector_manager import ConnectorManager
            result = ConnectorManager._create_single("kiwoom")
            assert result is mock_conn

    def test_create_single_unknown_broker_raises(self):
        mock_registry = {}
        with patch("backend.app.core.broker_registry.CONNECTOR_REGISTRY", mock_registry):
            from backend.app.core.connector_manager import ConnectorManager
            with pytest.raises(ValueError, match="지원하지 않는 증권사"):
                ConnectorManager._create_single("unknown")

    def test_create_single_no_create_connector_raises(self):
        # truthy dict이지만 create_connector 키가 없는 경우
        mock_registry = {"kiwoom": {"other_key": "value"}}
        with patch("backend.app.core.broker_registry.CONNECTOR_REGISTRY", mock_registry):
            from backend.app.core.connector_manager import ConnectorManager
            with pytest.raises(ValueError, match="create_connector"):
                ConnectorManager._create_single("kiwoom")


# ── 콜백 ───────────────────────────────────────────────────────────────────────

class TestCallbacks:
    def test_set_message_callback_sets_on_all_connectors(self):
        conn1 = _mock_connector()
        conn2 = _mock_connector()
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        cb = MagicMock()
        mgr.set_message_callback(cb)
        conn1.set_message_callback.assert_called_once_with(cb)
        conn2.set_message_callback.assert_called_once_with(cb)

    def test_set_message_callback_stores_callback(self):
        conn = _mock_connector()
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        cb = MagicMock()
        mgr.set_message_callback(cb)
        assert mgr._callback is cb

    def test_set_message_callback_empty_connectors(self):
        mgr = _make_manager_with_connectors({})
        cb = MagicMock()
        mgr.set_message_callback(cb)
        assert mgr._callback is cb

    def test_set_reconnect_callback_sets_on_supporting_connectors(self):
        conn1 = _mock_connector()
        conn2 = _mock_connector()
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        cb = MagicMock()
        mgr.set_reconnect_callback(cb)
        conn1.set_reconnect_success_callback.assert_called_once_with(cb)
        conn2.set_reconnect_success_callback.assert_called_once_with(cb)

    def test_set_reconnect_callback_skips_unsupported(self):
        conn = _mock_connector()
        del conn.set_reconnect_success_callback
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        cb = MagicMock()
        mgr.set_reconnect_callback(cb)  # 예외 발생하지 않아야 함


# ── connect_all ────────────────────────────────────────────────────────────────

class TestConnectAll:
    @pytest.mark.asyncio
    async def test_connect_all_success(self):
        conn1 = _mock_connector()
        conn2 = _mock_connector()
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        mgr.set_reconnect_callback = MagicMock()
        await mgr.connect_all()
        conn1.connect.assert_called_once()
        conn2.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_all_empty_connectors(self):
        mgr = _make_manager_with_connectors({})
        mgr.set_reconnect_callback = MagicMock()
        await mgr.connect_all()  # 예외 없이 반환

    @pytest.mark.asyncio
    async def test_connect_all_one_fails(self):
        conn1 = _mock_connector()
        conn2 = _mock_connector()
        conn2.connect = AsyncMock(side_effect=Exception("connect failed"))
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        mgr.set_reconnect_callback = MagicMock()
        await mgr.connect_all()  # 예외 전파 없이 완료
        conn1.connect.assert_called_once()
        conn2.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_all_sets_reconnect_callback(self):
        conn = _mock_connector()
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        mgr.set_reconnect_callback = MagicMock()
        await mgr.connect_all()
        mgr.set_reconnect_callback.assert_called_once()


# ── _on_reconnect_success ──────────────────────────────────────────────────────

class TestOnReconnectSuccess:
    @pytest.mark.asyncio
    async def test_reconnect_success_calls_restore(self):
        mgr = _make_manager_with_connectors({"kiwoom": _mock_connector()})
        with patch("backend.app.services.engine_ws_reg.restore_subscriptions_after_reconnect", new_callable=AsyncMock) as mock_restore:
            await mgr._on_reconnect_success("kiwoom")
            mock_restore.assert_called_once_with("kiwoom")

    @pytest.mark.asyncio
    async def test_reconnect_success_handles_exception(self):
        mgr = _make_manager_with_connectors({"kiwoom": _mock_connector()})
        with patch("backend.app.services.engine_ws_reg.restore_subscriptions_after_reconnect", new_callable=AsyncMock, side_effect=Exception("restore failed")):
            await mgr._on_reconnect_success("kiwoom")  # 예외 전파 없이 완료


# ── disconnect_all ─────────────────────────────────────────────────────────────

class TestDisconnectAll:
    @pytest.mark.asyncio
    async def test_disconnect_all_success(self):
        conn1 = _mock_connector()
        conn2 = _mock_connector()
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        await mgr.disconnect_all()
        conn1.disconnect.assert_called_once()
        conn2.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_all_empty(self):
        mgr = _make_manager_with_connectors({})
        await mgr.disconnect_all()  # 예외 없이 반환

    @pytest.mark.asyncio
    async def test_disconnect_all_one_fails(self):
        conn1 = _mock_connector()
        conn2 = _mock_connector()
        conn2.disconnect = AsyncMock(side_effect=Exception("disconnect failed"))
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        await mgr.disconnect_all()  # 예외 전파 없이 완료
        conn1.disconnect.assert_called_once()
        conn2.disconnect.assert_called_once()


# ── 상태 조회 ──────────────────────────────────────────────────────────────────

class TestStatusQuery:
    def test_is_connected_any_true(self):
        conn1 = _mock_connector(connected=False)
        conn2 = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        assert mgr.is_connected() is True

    def test_is_connected_all_false(self):
        conn1 = _mock_connector(connected=False)
        conn2 = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        assert mgr.is_connected() is False

    def test_is_connected_empty(self):
        mgr = _make_manager_with_connectors({})
        assert mgr.is_connected() is False

    def test_get_connector_returns_connector(self):
        conn = _mock_connector()
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        assert mgr.get_connector("kiwoom") is conn

    def test_get_connector_unknown_returns_none(self):
        mgr = _make_manager_with_connectors({"kiwoom": _mock_connector()})
        assert mgr.get_connector("ls") is None

    def test_active_broker_ids_returns_connected(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        assert mgr.active_broker_ids() == ["kiwoom"]

    def test_active_broker_ids_empty(self):
        mgr = _make_manager_with_connectors({})
        assert mgr.active_broker_ids() == []

    def test_broker_id_returns_first_active(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        assert mgr.broker_id == "kiwoom"

    def test_broker_id_none_when_all_disconnected(self):
        conn = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        assert mgr.broker_id is None


# ── send_message ───────────────────────────────────────────────────────────────

class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_message_routes_to_connected(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        result = await mgr.send_message({"type": "REG"})
        assert result is True
        conn1.send_message.assert_called_once_with({"type": "REG"})

    @pytest.mark.asyncio
    async def test_send_message_no_connected_returns_false(self):
        conn = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        result = await mgr.send_message({"type": "REG"})
        assert result is False


# ── subscribe_stocks ───────────────────────────────────────────────────────────

class TestSubscribeStocks:
    @pytest.mark.asyncio
    async def test_subscribe_single_connector(self):
        conn = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        result = await mgr.subscribe_stocks(["005930", "035420"])
        assert result is True
        conn.subscribe_stocks.assert_called_once_with(["005930", "035420"])
        assert mgr._sub_codes["kiwoom"] == {"005930", "035420"}

    @pytest.mark.asyncio
    async def test_subscribe_no_connected_returns_false(self):
        conn = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        result = await mgr.subscribe_stocks(["005930"])
        assert result is False

    @pytest.mark.asyncio
    async def test_subscribe_multiple_connectors_distributes(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        result = await mgr.subscribe_stocks(["A", "B", "C", "D"])
        assert result is True
        # 분산되어 호출되어야 함
        conn1.subscribe_stocks.assert_called_once()
        conn2.subscribe_stocks.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_multiple_one_fails(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=True)
        conn2.subscribe_stocks = AsyncMock(return_value=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        result = await mgr.subscribe_stocks(["A", "B", "C", "D"])
        assert result is False

    @pytest.mark.asyncio
    async def test_subscribe_tracks_sub_codes(self):
        conn = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        await mgr.subscribe_stocks(["005930"])
        await mgr.subscribe_stocks(["035420"])
        assert mgr._sub_codes["kiwoom"] == {"005930", "035420"}


# ── unsubscribe_stocks ─────────────────────────────────────────────────────────

class TestUnsubscribeStocks:
    @pytest.mark.asyncio
    async def test_unsubscribe_from_subscribed_connector(self):
        conn = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        mgr._sub_codes["kiwoom"] = {"005930", "035420"}
        result = await mgr.unsubscribe_stocks(["005930"])
        assert result is True
        conn.unsubscribe_stocks.assert_called_once_with(["005930"])
        assert "005930" not in mgr._sub_codes["kiwoom"]
        assert "035420" in mgr._sub_codes["kiwoom"]

    @pytest.mark.asyncio
    async def test_unsubscribe_no_match_falls_back_to_any(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        mgr._sub_codes = {"kiwoom": set(), "ls": set()}
        result = await mgr.unsubscribe_stocks(["005930"])
        assert result is True
        # 어느 한 커넥터에서 호출되어야 함
        assert conn1.unsubscribe_stocks.called or conn2.unsubscribe_stocks.called

    @pytest.mark.asyncio
    async def test_unsubscribe_all_codes(self):
        conn = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        mgr._sub_codes["kiwoom"] = {"005930", "035420"}
        result = await mgr.unsubscribe_stocks(["005930", "035420"])
        assert result is True
        assert len(mgr._sub_codes["kiwoom"]) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_failure_returns_false(self):
        conn = _mock_connector(connected=True)
        conn.unsubscribe_stocks = AsyncMock(return_value=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        mgr._sub_codes["kiwoom"] = {"005930"}
        result = await mgr.unsubscribe_stocks(["005930"])
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_not_connected_skipped(self):
        conn = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        mgr._sub_codes["kiwoom"] = {"005930"}
        result = await mgr.unsubscribe_stocks(["005930"])
        assert result is True  # remaining이 비어있지 않지만 연결된 커넥터가 없어 fallback도 없음 → all_ok True
        # 실제로는 remaining이 남아있지만 연결된 커넥터가 없으므로 all_ok는 True로 유지


# ── subscribe_account / subscribe_index ────────────────────────────────────────

class TestSubscribeAccountIndex:
    @pytest.mark.asyncio
    async def test_subscribe_account_routes_to_connected(self):
        conn = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        result = await mgr.subscribe_account()
        assert result is True
        conn.subscribe_account.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_account_no_connected_returns_false(self):
        conn = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        result = await mgr.subscribe_account()
        assert result is False

    @pytest.mark.asyncio
    async def test_subscribe_index_routes_to_connected(self):
        conn = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        result = await mgr.subscribe_index()
        assert result is True
        conn.subscribe_index.assert_called_once()


# ── supports_ack ───────────────────────────────────────────────────────────────

class TestSupportsAck:
    def test_supports_ack_any_true(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=True)
        conn2.supports_ack = MagicMock(return_value=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        assert mgr.supports_ack() is True

    def test_supports_ack_all_false(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=True)
        conn1.supports_ack = MagicMock(return_value=False)
        conn2.supports_ack = MagicMock(return_value=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        assert mgr.supports_ack() is False

    def test_supports_ack_no_connected(self):
        conn = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        assert mgr.supports_ack() is False


# ── unsubscribe_all ────────────────────────────────────────────────────────────

class TestUnsubscribeAll:
    @pytest.mark.asyncio
    async def test_unsubscribe_all_success(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        mgr._sub_codes = {"kiwoom": {"A"}, "ls": {"B"}}
        result = await mgr.unsubscribe_all()
        assert result is True
        conn1.unsubscribe_all.assert_called_once()
        conn2.unsubscribe_all.assert_called_once()
        assert "kiwoom" not in mgr._sub_codes
        assert "ls" not in mgr._sub_codes

    @pytest.mark.asyncio
    async def test_unsubscribe_all_all_fail(self):
        conn = _mock_connector(connected=True)
        conn.unsubscribe_all = AsyncMock(return_value=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        result = await mgr.unsubscribe_all()
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_all_clears_sub_codes_even_if_disconnected(self):
        conn = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        mgr._sub_codes = {"kiwoom": {"A"}}
        await mgr.unsubscribe_all()
        assert "kiwoom" not in mgr._sub_codes


# ── subscribe_dynamic / unsubscribe_dynamic ────────────────────────────────────

class TestSubscribeDynamic:
    @pytest.mark.asyncio
    async def test_subscribe_dynamic_routes_to_connected(self):
        conn1 = _mock_connector(connected=True)
        conn2 = _mock_connector(connected=False)
        mgr = _make_manager_with_connectors({"kiwoom": conn1, "ls": conn2})
        await mgr.subscribe_dynamic(["005930"])
        conn1.subscribe_dynamic.assert_called_once_with(["005930"])
        conn2.subscribe_dynamic.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_dynamic_routes_to_connected(self):
        conn = _mock_connector(connected=True)
        mgr = _make_manager_with_connectors({"kiwoom": conn})
        await mgr.unsubscribe_dynamic(["005930"])
        conn.unsubscribe_dynamic.assert_called_once_with(["005930"])
