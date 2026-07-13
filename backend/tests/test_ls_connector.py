"""ls_connector.py 단위 테스트 — LS증권 WebSocket 커넥터 검증.

_LsSocket: __init__, connect, disconnect, send, _recv_loop, _convert_ls_to_internal
LsConnector: __init__, broker_id, is_connected, supports_ack, realtime/auto_trade 설정,
  connect, disconnect, send_message, subscribe/unsubscribe 계열, register/unregister_account,
  subscribe_jif, subscribe_index, _on_ws_message, _on_socket_disconnect, _reconnect_loop,
  set_*_callback, _format_code, _get_token_async
create_ls_connector: 정상 생성, app_key/secret 없음

의존성: websockets, engine_state, ws_subscribe_control, daily_time_scheduler,
  engine_symbol_utils, broker_factory, broker_urls, ls_rest
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 헬퍼 ───────────────────────────────────────────────────────────────────────

def _mock_websockets_module():
    """websockets 모듈 mock 생성."""
    mock_mod = MagicMock()
    mock_mod.connect = AsyncMock()
    closed_exc = type("ConnectionClosed", (Exception,), {})
    mock_mod.exceptions = MagicMock()
    mock_mod.exceptions.ConnectionClosed = closed_exc
    return mock_mod, closed_exc


def _mock_ws_connection():
    """websockets connection mock 생성."""
    ws = AsyncMock()
    ws.send = AsyncMock()
    ws.close = AsyncMock()
    ws.recv = AsyncMock()
    return ws


def _make_ls_socket(uri="wss://test", token="tok", on_message=None, on_disconnect=None, queue_callback=None):
    """_LsSocket 인스턴스 생성."""
    from backend.app.core.ls_connector import _LsSocket
    return _LsSocket(
        uri=uri,
        token=token,
        on_message=on_message or AsyncMock(),
        on_disconnect=on_disconnect,
        queue_callback=queue_callback,
    )


def _make_ls_connector(app_key="key", app_secret="secret", ws_uri="wss://test"):
    """LsConnector 인스턴스 생성."""
    from backend.app.core.ls_connector import LsConnector
    return LsConnector(app_key=app_key, app_secret=app_secret, ws_uri=ws_uri)


# ── _LsSocket.__init__ ─────────────────────────────────────────────────────────

class TestLsSocketInit:
    def test_init_stores_params(self):
        on_msg = AsyncMock()
        on_disc = AsyncMock()
        q_cb = MagicMock()
        sock = _make_ls_socket(uri="wss://x", token="t", on_message=on_msg, on_disconnect=on_disc, queue_callback=q_cb)
        assert sock._uri == "wss://x"
        assert sock._token == "t"
        assert sock._on_message is on_msg
        assert sock._on_disconnect is on_disc
        assert sock._queue_callback is q_cb
        assert sock.connected is False
        assert sock._ws is None
        assert sock._recv_task is None

    def test_init_defaults_on_disconnect_and_queue(self):
        sock = _make_ls_socket()
        assert sock._on_disconnect is None
        assert sock._queue_callback is None


# ── _LsSocket.connect ──────────────────────────────────────────────────────────

class TestLsSocketConnect:
    async def test_connect_success(self):
        mock_ws = _mock_ws_connection()
        mock_mod, _ = _mock_websockets_module()
        mock_mod.connect.return_value = mock_ws
        with patch("backend.app.core.ls_connector.websockets", mock_mod):
            sock = _make_ls_socket()
            with patch.object(sock, "_recv_loop", new_callable=AsyncMock):
                await sock.connect()
            assert sock.connected is True
            assert sock._ws is mock_ws
            mock_mod.connect.assert_called_once()

    async def test_connect_no_websockets_raises(self):
        with patch("backend.app.core.ls_connector.websockets", None):
            sock = _make_ls_socket()
            with pytest.raises(RuntimeError, match="websockets"):
                await sock.connect()

    async def test_connect_clears_stop_event(self):
        mock_ws = _mock_ws_connection()
        mock_mod, _ = _mock_websockets_module()
        mock_mod.connect.return_value = mock_ws
        with patch("backend.app.core.ls_connector.websockets", mock_mod):
            sock = _make_ls_socket()
            sock._stop_event.set()
            with patch.object(sock, "_recv_loop", new_callable=AsyncMock):
                await sock.connect()
            assert sock._stop_event.is_set() is False


# ── _LsSocket.disconnect ───────────────────────────────────────────────────────

class TestLsSocketDisconnect:
    async def test_disconnect_normal(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        sock._ws = mock_ws
        sock.connected = True

        class _FakeTask:
            def __init__(self):
                self.cancel_called = False
            def done(self):
                return False
            def cancel(self):
                self.cancel_called = True
            def __await__(self):
                if False:
                    yield  # pragma: no cover
                raise asyncio.CancelledError()

        fake_task = _FakeTask()
        sock._recv_task = fake_task
        await sock.disconnect()
        assert sock.connected is False
        assert sock._recv_task is None
        assert sock._ws is None
        assert fake_task.cancel_called is True
        mock_ws.close.assert_called_once()

    async def test_disconnect_recv_task_done(self):
        sock = _make_ls_socket()
        mock_task = MagicMock()
        mock_task.done.return_value = True
        sock._recv_task = mock_task
        await sock.disconnect()
        mock_task.cancel.assert_not_called()

    async def test_disconnect_ws_close_failure(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.close.side_effect = Exception("close fail")
        sock._ws = mock_ws
        sock.connected = True
        await sock.disconnect()
        assert sock._ws is None


# ── _LsSocket.send ─────────────────────────────────────────────────────────────

class TestLsSocketSend:
    async def test_send_success(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        sock._ws = mock_ws
        sock.connected = True
        result = await sock.send({"header": {}, "body": {"tr_cd": "US3"}})
        assert result is True
        mock_ws.send.assert_called_once()

    async def test_send_not_connected(self):
        sock = _make_ls_socket()
        sock._ws = _mock_ws_connection()
        sock.connected = False
        result = await sock.send({"body": {"tr_cd": "US3"}})
        assert result is False

    async def test_send_no_ws(self):
        sock = _make_ls_socket()
        sock.connected = True
        sock._ws = None
        result = await sock.send({"body": {"tr_cd": "US3"}})
        assert result is False


# ── _LsSocket._recv_loop ───────────────────────────────────────────────────────

class TestLsSocketRecvLoop:
    async def test_string_ping_responded(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = ["PING", asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        mock_ws.send.assert_called_with("PING")

    async def test_json_ping_responded(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        ping_msg = json.dumps({"trnm": "PING"})
        mock_ws.recv.side_effect = [ping_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        mock_ws.send.assert_called_with(ping_msg)

    async def test_list_message_skipped(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = ["[1,2,3]", asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_not_called()

    async def test_jif_direct_callback(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        jif_msg = json.dumps({"header": {"tr_cd": "JIF"}, "body": {"jangubun": "1", "jstatus": "1"}})
        mock_ws.recv.side_effect = [jif_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        q_cb = MagicMock()
        sock._queue_callback = q_cb
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_called_once()
        called_msg = on_msg.call_args[0][0]
        assert called_msg["trnm"] == "JIF"
        q_cb.assert_not_called()

    async def test_queue_callback_used(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        us3_msg = json.dumps({"header": {"tr_cd": "US3"}, "body": {"shcode": "005930", "price": "70000"}})
        mock_ws.recv.side_effect = [us3_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        q_cb = MagicMock()
        sock._queue_callback = q_cb
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        q_cb.assert_called_once()
        on_msg.assert_not_called()

    async def test_fallback_on_message_when_no_queue(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        us3_msg = json.dumps({"header": {"tr_cd": "US3"}, "body": {"shcode": "005930", "price": "70000"}})
        mock_ws.recv.side_effect = [us3_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        sock._queue_callback = None
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_called_once()

    async def test_connection_closed_triggers_on_disconnect(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        _, closed_cls = _mock_websockets_module()
        mock_ws.recv.side_effect = closed_cls("closed")
        sock._ws = mock_ws
        sock.connected = True
        on_disc = AsyncMock()
        sock._on_disconnect = on_disc
        with patch("backend.app.core.ls_connector._WsConnectionClosed", closed_cls):
            await sock._recv_loop()
        assert sock.connected is False
        on_disc.assert_called_once()

    async def test_connection_closed_no_on_disconnect(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        _, closed_cls = _mock_websockets_module()
        mock_ws.recv.side_effect = closed_cls("closed")
        sock._ws = mock_ws
        sock.connected = True
        sock._on_disconnect = None
        with patch("backend.app.core.ls_connector._WsConnectionClosed", closed_cls):
            await sock._recv_loop()
        assert sock.connected is False

    async def test_non_connection_error_continues_loop(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = [ValueError("test error"), asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        with patch("backend.app.core.ls_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await sock._recv_loop()
        # ValueError should not set connected=False
        assert sock.connected is True

    async def test_json_decode_error_skipped(self):
        sock = _make_ls_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = ["not_json{{{", asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_not_called()


# ── _LsSocket._convert_ls_to_internal ──────────────────────────────────────────

class TestConvertLsToInternal:
    def test_empty_body_returns_none(self):
        sock = _make_ls_socket()
        assert sock._convert_ls_to_internal("US3", {}, None) is None

    def test_unknown_tr_cd_returns_none(self):
        sock = _make_ls_socket()
        assert sock._convert_ls_to_internal("XXX", {}, {"data": "test"}) is None

    def test_us3_normal(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("US3", {}, {
            "shcode": "005930", "price": "70000", "value": "1000000",
            "sign": "2", "change": "1000", "drate": "1.5",
            "high": "71000", "offerho": "69000", "bidho": "68000", "cpower": "120.5",
        })
        assert result is not None
        assert result["trnm"] == "REAL"
        assert result["data"][0]["type"] == "0B"
        assert result["data"][0]["code"] == "005930"
        vals = result["data"][0]["values"]
        assert vals["10"] == "+70000"
        assert vals["11"] == "+1000"
        assert vals["12"] == "+1.5"

    def test_us3_no_shcode_returns_none(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("US3", {}, {"price": "70000"})
        assert result is None

    def test_us3_drate_zero_with_change_calculated(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("US3", {}, {
            "shcode": "005930", "price": "70000", "value": "1000000",
            "sign": "2", "change": "1000", "drate": "0",
            "high": "71000", "offerho": "69000", "bidho": "68000", "cpower": "0",
        })
        assert result is not None
        vals = result["data"][0]["values"]
        # drate = (1000 / (70000 - 1000)) * 100 ≈ 1.45
        assert float(vals["12"]) > 0

    def test_us3_sign_4_5_negative(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("US3", {}, {
            "shcode": "005930", "price": "69000", "value": "500000",
            "sign": "5", "change": "1000", "drate": "1.43",
            "high": "70000", "offerho": "69000", "bidho": "68000", "cpower": "0",
        })
        vals = result["data"][0]["values"]
        assert vals["10"] == "-69000"
        assert vals["11"] == "-1000"
        assert vals["12"] == "-1.43"

    def test_us3_sign_3_no_prefix(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("US3", {}, {
            "shcode": "005930", "price": "70000", "value": "500000",
            "sign": "3", "change": "0", "drate": "0",
            "high": "70000", "offerho": "70000", "bidho": "70000", "cpower": "0",
        })
        vals = result["data"][0]["values"]
        assert vals["10"] == "70000"
        assert vals["11"] == "0"

    def test_uh1_normal(self):
        sock = _make_ls_socket()
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = sock._convert_ls_to_internal("UH1", {}, {
                "shcode": "U005930   ", "unt_totofferrem": "1000", "unt_totbidrem": "2000",
            })
        assert result is not None
        assert result["data"][0]["type"] == "0D"
        assert result["data"][0]["code"] == "005930"
        assert result["data"][0]["values"]["121"] == "1000"
        assert result["data"][0]["values"]["125"] == "2000"

    def test_uh1_no_shcode_returns_none(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("UH1", {}, {"unt_totofferrem": "1000"})
        assert result is None

    def test_uh1_ex_shcode_fallback(self):
        sock = _make_ls_socket()
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = sock._convert_ls_to_internal("UH1", {}, {
                "ex_shcode": "U005930   ", "unt_totofferrem": "500", "unt_totbidrem": "600",
            })
        assert result is not None
        assert result["data"][0]["code"] == "005930"

    def test_uph_normal(self):
        sock = _make_ls_socket()
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = sock._convert_ls_to_internal("UPH", {}, {
                "shcode": "U005930   ", "tval": "50000000",
            })
        assert result is not None
        assert result["data"][0]["type"] == "PGM"
        assert result["data"][0]["values"]["tval"] == "50000000"

    def test_uph_no_shcode_returns_none(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("UPH", {}, {"tval": "100"})
        assert result is None

    def test_jif_normal(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("JIF", {}, {"jangubun": "1", "jstatus": "1"})
        assert result is not None
        assert result["trnm"] == "JIF"
        assert result["jangubun"] == "1"
        assert result["jstatus"] == "1"

    def test_jif_empty_jangubun_returns_none(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("JIF", {}, {"jangubun": "", "jstatus": "1"})
        assert result is None

    def test_ij_normal(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("IJ_", {}, {
            "upcode": "001", "jisu": "2500", "change": "10", "drate": "0.4", "sign": "2",
        })
        assert result is not None
        assert result["data"][0]["type"] == "0J"
        assert result["data"][0]["item"] == "001"
        assert result["data"][0]["values"]["10"] == "2500"

    def test_ij_no_upcode_returns_none(self):
        sock = _make_ls_socket()
        result = sock._convert_ls_to_internal("IJ_", {}, {"jisu": "2500"})
        assert result is None


# ── LsConnector.__init__ / 기본 속성 ───────────────────────────────────────────

class TestLsConnectorInit:
    def test_init_stores_params(self):
        conn = _make_ls_connector(app_key="mykey", app_secret="mysecret", ws_uri="wss://custom")
        assert conn._app_key == "mykey"
        assert conn._app_secret == "mysecret"
        assert conn._ws_uri == "wss://custom"
        assert conn._connected is False
        assert conn._socket is None
        assert conn._token is None
        assert conn._realtime_enabled is True
        assert conn._auto_trade_enabled is True

    def test_init_default_ws_uri(self):
        with patch("backend.app.core.broker_urls.build_broker_urls", return_value={"ws_uri": "wss://ls-default"}):
            from backend.app.core.ls_connector import LsConnector
            conn = LsConnector(app_key="k", app_secret="s")
            assert conn._ws_uri == "wss://ls-default"

    def test_broker_id(self):
        conn = _make_ls_connector()
        assert conn.broker_id == "ls"

    def test_is_connected_false_when_no_socket(self):
        conn = _make_ls_connector()
        assert conn.is_connected() is False

    def test_is_connected_true_when_socket_connected(self):
        conn = _make_ls_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        assert conn.is_connected() is True

    def test_is_connected_false_when_socket_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = False
        conn._socket = mock_socket
        assert conn.is_connected() is False

    def test_supports_ack(self):
        conn = _make_ls_connector()
        assert conn.supports_ack() is False


# ── LsConnector realtime / auto_trade 설정 ─────────────────────────────────────

class TestLsConnectorSettings:
    def test_is_realtime_enabled_default(self):
        conn = _make_ls_connector()
        assert conn.is_realtime_enabled() is True

    def test_set_realtime_enabled(self):
        conn = _make_ls_connector()
        conn.set_realtime_enabled(False)
        assert conn.is_realtime_enabled() is False

    def test_is_auto_trade_enabled_default(self):
        conn = _make_ls_connector()
        assert conn.is_auto_trade_enabled() is True

    def test_set_auto_trade_enabled(self):
        conn = _make_ls_connector()
        conn.set_auto_trade_enabled(False)
        assert conn.is_auto_trade_enabled() is False


# ── LsConnector.connect ────────────────────────────────────────────────────────

class TestLsConnectorConnect:
    async def test_connect_success(self):
        conn = _make_ls_connector()
        with (
            patch.object(conn, "_get_token_async", AsyncMock(return_value="tok123")),
            patch("backend.app.core.ls_connector._LsSocket") as mock_sock_cls,
            patch("backend.app.services.engine_state.state", MagicMock()),
            patch("backend.app.services.engine_state._notify_reg_ack", MagicMock()),
            patch("backend.app.services.daily_time_scheduler._trigger_reg_pipeline", MagicMock()),
            patch.object(conn, "subscribe_jif", AsyncMock()),
            patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()),
        ):
            mock_socket = AsyncMock()
            mock_socket.connect = AsyncMock()
            mock_sock_cls.return_value = mock_socket
            await conn.connect()
            assert conn._connected is True
            assert conn._token == "tok123"
            mock_socket.connect.assert_called_once()

    async def test_connect_already_connected(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._lock = asyncio.Lock()
        with (
            patch.object(conn, "_get_token_async", AsyncMock(return_value="tok")) as mock_token,
            patch("backend.app.core.ls_connector._LsSocket") as mock_sock_cls,
        ):
            await conn.connect()
            mock_token.assert_not_called()
            mock_sock_cls.assert_not_called()

    async def test_connect_token_failure_raises(self):
        conn = _make_ls_connector()
        with (
            patch.object(conn, "_get_token_async", AsyncMock(return_value=None)),
        ):
            with pytest.raises(ConnectionError, match="토큰"):
                await conn.connect()

    async def test_connect_socket_failure_triggers_reconnect(self):
        conn = _make_ls_connector()
        with (
            patch.object(conn, "_get_token_async", AsyncMock(return_value="tok")),
            patch("backend.app.core.ls_connector._LsSocket") as mock_sock_cls,
            patch.object(conn, "_on_socket_disconnect", AsyncMock()),
        ):
            mock_socket = AsyncMock()
            mock_socket.connect.side_effect = Exception("connect fail")
            mock_sock_cls.return_value = mock_socket
            with pytest.raises(Exception, match="connect fail"):
                await conn.connect()
            assert conn._connected is False


# ── LsConnector.disconnect ─────────────────────────────────────────────────────

class TestLsConnectorDisconnect:
    async def test_disconnect_normal(self):
        conn = _make_ls_connector()
        mock_socket = AsyncMock()
        conn._socket = mock_socket
        conn._connected = True
        with patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()):
            await conn.disconnect()
            assert conn._connected is False
            assert conn._socket is None
            mock_socket.disconnect.assert_called_once()

    async def test_disconnect_no_socket(self):
        conn = _make_ls_connector()
        conn._connected = True
        with patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()):
            await conn.disconnect()
            assert conn._connected is False


# ── LsConnector.send_message ───────────────────────────────────────────────────

class TestLsConnectorSendMessage:
    async def test_send_message_success(self):
        conn = _make_ls_connector()
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        result = await conn.send_message({"test": "payload"})
        assert result is True
        mock_socket.send.assert_called_once_with({"test": "payload"})

    async def test_send_message_no_socket(self):
        conn = _make_ls_connector()
        conn._socket = None
        result = await conn.send_message({"test": "payload"})
        assert result is False


# ── LsConnector.subscribe / unsubscribe (하위 호환) ─────────────────────────────

class TestLsConnectorSubscribeCompat:
    async def test_subscribe_delegates_to_subscribe_stocks(self):
        conn = _make_ls_connector()
        with patch.object(conn, "subscribe_stocks", AsyncMock(return_value=True)) as mock_sub:
            result = await conn.subscribe("005930", ["0B"])
            mock_sub.assert_called_once_with(["005930"])
            assert result is True

    async def test_unsubscribe_delegates_to_unsubscribe_stocks(self):
        conn = _make_ls_connector()
        with patch.object(conn, "unsubscribe_stocks", AsyncMock(return_value=True)) as mock_unsub:
            result = await conn.unsubscribe("005930", ["0B"])
            mock_unsub.assert_called_once_with(["005930"])
            assert result is True


# ── LsConnector.subscribe_stocks / unsubscribe_stocks ──────────────────────────

class TestLsConnectorSubscribeStocks:
    async def test_subscribe_stocks_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = await conn.subscribe_stocks(["005930"])
        assert result is True
        mock_socket.send.assert_called_once()
        payload = mock_socket.send.call_args[0][0]
        assert payload["header"]["tr_type"] == "3"
        assert payload["body"]["tr_cd"] == "US3"

    async def test_subscribe_stocks_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.subscribe_stocks(["005930"])
        assert result is False

    async def test_subscribe_stocks_multiple(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", side_effect=["005930", "000660"]):
            result = await conn.subscribe_stocks(["005930", "000660"])
        assert result is True
        assert mock_socket.send.call_count == 2

    async def test_subscribe_stocks_partial_failure(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.side_effect = [True, False]
        conn._socket = mock_socket
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", side_effect=["005930", "000660"]):
            result = await conn.subscribe_stocks(["005930", "000660"])
        assert result is False

    async def test_unsubscribe_stocks_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = await conn.unsubscribe_stocks(["005930"])
        assert result is True
        payload = mock_socket.send.call_args[0][0]
        assert payload["header"]["tr_type"] == "4"

    async def test_unsubscribe_stocks_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.unsubscribe_stocks(["005930"])
        assert result is False


# ── LsConnector.subscribe_stocks_tr / unsubscribe_stocks_tr ────────────────────

class TestLsConnectorSubscribeStocksTr:
    async def test_subscribe_stocks_tr_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = await conn.subscribe_stocks_tr(["005930"], "UH1")
        # 반환값: (success_count, fail_count)
        assert result == (1, 0)
        payload = mock_socket.send.call_args[0][0]
        assert payload["body"]["tr_cd"] == "UH1"

    async def test_subscribe_stocks_tr_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.subscribe_stocks_tr(["005930"], "UH1")
        # 연결 없음 → (0, fail_count=len(codes))
        assert result == (0, 1)

    async def test_unsubscribe_stocks_tr_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = await conn.unsubscribe_stocks_tr(["005930"], "UPH")
        # 반환값: (success_count, fail_count)
        assert result == (1, 0)
        payload = mock_socket.send.call_args[0][0]
        assert payload["body"]["tr_cd"] == "UPH"
        assert payload["header"]["tr_type"] == "4"

    async def test_unsubscribe_stocks_tr_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.unsubscribe_stocks_tr(["005930"], "UPH")
        # 연결 없음 → (0, fail_count=len(codes))
        assert result == (0, 1)


# ── LsConnector.subscribe_dynamic / unsubscribe_dynamic ────────────────────────

class TestLsConnectorSubscribeDynamic:
    async def test_subscribe_dynamic_success(self):
        conn = _make_ls_connector()
        with (
            patch.object(conn, "subscribe_stocks_tr", AsyncMock(return_value=(1, 0))) as mock_sub,
        ):
            await conn.subscribe_dynamic(["005930", "000660"])
            assert mock_sub.call_count == 2
            assert mock_sub.call_args_list[0][0][1] == "UH1"
            assert mock_sub.call_args_list[1][0][1] == "UPH"

    async def test_subscribe_dynamic_empty_codes(self):
        conn = _make_ls_connector()
        with patch.object(conn, "subscribe_stocks_tr", AsyncMock(return_value=(0, 0))) as mock_sub:
            await conn.subscribe_dynamic([])
            mock_sub.assert_not_called()

    async def test_unsubscribe_dynamic_success(self):
        conn = _make_ls_connector()
        with (
            patch.object(conn, "unsubscribe_stocks_tr", AsyncMock(return_value=(1, 0))) as mock_unsub,
        ):
            await conn.unsubscribe_dynamic(["005930"])
            assert mock_unsub.call_count == 2

    async def test_unsubscribe_dynamic_empty_codes(self):
        conn = _make_ls_connector()
        with patch.object(conn, "unsubscribe_stocks_tr", AsyncMock(return_value=(0, 0))) as mock_unsub:
            await conn.unsubscribe_dynamic([])
            mock_unsub.assert_not_called()


# ── LsConnector.register_account / unregister_account ──────────────────────────

class TestLsConnectorRegisterAccount:
    async def test_register_account_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        result = await conn.register_account("SC0")
        assert result is True
        payload = mock_socket.send.call_args[0][0]
        assert payload["header"]["tr_type"] == "1"
        assert payload["body"]["tr_cd"] == "SC0"

    async def test_register_account_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.register_account()
        assert result is False

    async def test_register_account_default_tr_cd(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        await conn.register_account()
        payload = mock_socket.send.call_args[0][0]
        assert payload["body"]["tr_cd"] == "SC0"

    async def test_unregister_account_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        result = await conn.unregister_account("SC1")
        assert result is True
        payload = mock_socket.send.call_args[0][0]
        assert payload["header"]["tr_type"] == "2"

    async def test_unregister_account_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.unregister_account()
        assert result is False


# ── LsConnector.subscribe_jif / subscribe_index ────────────────────────────────

class TestLsConnectorSubscribeJifIndex:
    async def test_subscribe_jif_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        result = await conn.subscribe_jif()
        assert result is True
        payload = mock_socket.send.call_args[0][0]
        assert payload["body"]["tr_cd"] == "JIF"
        assert payload["body"]["tr_key"] == "0"

    async def test_subscribe_jif_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.subscribe_jif()
        assert result is False

    async def test_subscribe_index_success(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        result = await conn.subscribe_index()
        assert result is True
        assert mock_socket.send.call_count == 2
        codes = [c[0][0]["body"]["tr_key"] for c in mock_socket.send.call_args_list]
        assert "001" in codes
        assert "301" in codes

    async def test_subscribe_index_not_connected(self):
        conn = _make_ls_connector()
        conn._connected = False
        result = await conn.subscribe_index()
        assert result is False

    async def test_subscribe_index_partial_failure(self):
        conn = _make_ls_connector()
        conn._connected = True
        conn._token = "tok"
        mock_socket = AsyncMock()
        mock_socket.send.side_effect = [True, False]
        conn._socket = mock_socket
        result = await conn.subscribe_index()
        assert result is False


# ── LsConnector._on_ws_message ─────────────────────────────────────────────────

class TestLsConnectorOnWsMessage:
    async def test_async_callback(self):
        conn = _make_ls_connector()
        cb = AsyncMock()
        conn._receive_callback = cb
        await conn._on_ws_message({"trnm": "REAL"})
        cb.assert_called_once_with({"trnm": "REAL"})
        assert conn._received_count == 1

    async def test_sync_callback(self):
        conn = _make_ls_connector()
        cb = MagicMock()
        conn._receive_callback = cb
        await conn._on_ws_message({"trnm": "REAL"})
        cb.assert_called_once_with({"trnm": "REAL"})

    async def test_no_callback(self):
        conn = _make_ls_connector()
        conn._receive_callback = None
        await conn._on_ws_message({"trnm": "REAL"})
        assert conn._received_count == 1


# ── LsConnector._on_socket_disconnect ──────────────────────────────────────────

class TestLsConnectorOnSocketDisconnect:
    async def test_stop_reconnect_prevents_reconnect(self):
        conn = _make_ls_connector()
        conn._stop_reconnect = True
        with patch.object(conn, "_reconnect_loop", AsyncMock()) as mock_reconnect:
            await conn._on_socket_disconnect()
            mock_reconnect.assert_not_called()

    async def test_normal_disconnect_triggers_reconnect(self):
        conn = _make_ls_connector()
        conn._connected = True
        with (
            patch("backend.app.services.engine_state.state", MagicMock()),
            patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()),
            patch.object(conn, "_reconnect_loop", AsyncMock()) as mock_reconnect,
        ):
            await conn._on_socket_disconnect()
            assert conn._connected is False
            mock_reconnect.assert_called_once()

    async def test_already_reconnecting_skips(self):
        conn = _make_ls_connector()
        conn._reconnecting = True
        with (
            patch("backend.app.services.engine_state.state", MagicMock()),
            patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()),
            patch.object(conn, "_reconnect_loop", AsyncMock()) as mock_reconnect,
        ):
            await conn._on_socket_disconnect()
            mock_reconnect.assert_not_called()


# ── LsConnector._reconnect_loop ────────────────────────────────────────────────

class TestLsConnectorReconnectLoop:
    async def test_stop_signal_immediately(self):
        conn = _make_ls_connector()
        conn._stop_reconnect = True
        with patch("backend.app.core.ls_connector.asyncio.sleep", new_callable=AsyncMock):
            await conn._reconnect_loop()
        # Should return without any reconnect attempt

    async def test_token_failure_continues(self):
        conn = _make_ls_connector()
        conn._stop_reconnect = False
        call_count = 0

        async def mock_sleep(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                conn._stop_reconnect = True

        with (
            patch("backend.app.core.ls_connector.asyncio.sleep", new=mock_sleep),
            patch.object(conn, "_get_token_async", AsyncMock(return_value=None)),
        ):
            await conn._reconnect_loop()


# ── LsConnector.set_*_callback ─────────────────────────────────────────────────

class TestLsConnectorCallbacks:
    def test_set_reconnect_success_callback(self):
        conn = _make_ls_connector()
        cb = MagicMock()
        conn.set_reconnect_success_callback(cb)
        assert conn._on_reconnect_success is cb

    def test_set_message_callback(self):
        conn = _make_ls_connector()
        cb = MagicMock()
        conn.set_message_callback(cb)
        assert conn._receive_callback is cb

    def test_set_queue_callback(self):
        conn = _make_ls_connector()
        q = asyncio.Queue()
        conn.set_queue_callback(q)
        assert conn._ws_queue is q


# ── LsConnector._format_code ───────────────────────────────────────────────────

class TestLsConnectorFormatCode:
    def test_format_6digit_numeric(self):
        conn = _make_ls_connector()
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            result = conn._format_code("005930")
            assert result == "U005930   "

    def test_format_6digit_alpha(self):
        conn = _make_ls_connector()
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="0017J0"):
            result = conn._format_code("0017J0")
            assert result == "U0017J0   "

    def test_format_non_6digit_passthrough(self):
        conn = _make_ls_connector()
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="123"):
            result = conn._format_code("123")
            assert result == "123"


# ── LsConnector._get_token_async ───────────────────────────────────────────────

class TestLsConnectorGetToken:
    async def test_reuse_broker_rest_apis(self):
        conn = _make_ls_connector()
        mock_state = MagicMock()
        mock_rest = AsyncMock()
        mock_rest.ensure_token = AsyncMock(return_value=True)
        mock_rest.get_token = MagicMock(return_value="tok123")
        mock_state.broker_rest_apis = {"ls": mock_rest}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await conn._get_token_async()
        assert result == "tok123"

    async def test_auth_cache_fallback(self):
        conn = _make_ls_connector()
        mock_state = MagicMock()
        mock_state.broker_rest_apis = {}
        mock_router = MagicMock()
        mock_auth = MagicMock()
        mock_rest = AsyncMock()
        mock_rest.ensure_token = AsyncMock(return_value=True)
        mock_rest.get_token = MagicMock(return_value="tok456")
        mock_auth.rest_api = mock_rest
        mock_router._auth_cache = {"ls": mock_auth}
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_factory.get_router", MagicMock(return_value=mock_router)),
        ):
            result = await conn._get_token_async()
        assert result == "tok456"

    async def test_new_ls_rest_fallback(self):
        conn = _make_ls_connector()
        mock_state = MagicMock()
        mock_state.broker_rest_apis = {}
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_factory.get_router", MagicMock(side_effect=Exception("no router"))),
            patch("backend.app.core.ls_rest.LsRestAPI") as mock_cls,
        ):
            mock_api = AsyncMock()
            mock_api.ensure_token = AsyncMock(return_value=True)
            mock_api.get_token = MagicMock(return_value="tok789")
            mock_cls.return_value = mock_api
            result = await conn._get_token_async()
        assert result == "tok789"

    async def test_all_paths_fail_returns_none(self):
        conn = _make_ls_connector()
        mock_state = MagicMock()
        mock_state.broker_rest_apis = {}
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_factory.get_router", MagicMock(side_effect=Exception("no router"))),
            patch("backend.app.core.ls_rest.LsRestAPI") as mock_cls,
        ):
            mock_api = AsyncMock()
            mock_api.ensure_token = AsyncMock(return_value=False)
            mock_cls.return_value = mock_api
            result = await conn._get_token_async()
        assert result is None


# ── create_ls_connector ────────────────────────────────────────────────────────

class TestCreateLsConnector:
    def test_create_success(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {
            "ls_app_key": "mykey",
            "ls_app_secret": "mysecret",
        }
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_urls.build_broker_urls", return_value={"ws_uri": "wss://ls"}),
        ):
            from backend.app.core.ls_connector import create_ls_connector
            conn = create_ls_connector()
            assert conn._app_key == "mykey"
            assert conn._app_secret == "mysecret"
            assert conn._ws_uri == "wss://ls"

    def test_create_no_credentials_raises(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_urls.build_broker_urls", return_value={"ws_uri": "wss://ls"}),
        ):
            from backend.app.core.ls_connector import create_ls_connector
            with pytest.raises(ValueError, match="app_key"):
                create_ls_connector()
