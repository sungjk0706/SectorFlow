"""kiwoom_connector.py 단위 테스트 — 키움증권 WebSocket 커넥터 검증.

_KiwoomSocket: __init__, connect, disconnect, send, _recv_loop
KiwoomConnector: __init__, broker_id, is_connected, supports_ack, realtime/auto_trade 설정,
  connect, disconnect, send_message, subscribe/unsubscribe 계열, subscribe_dynamic/unsubscribe_dynamic,
  subscribe_index, _on_ws_message, _on_socket_disconnect, _reconnect_loop,
  set_*_callback, _format_code, _get_token_async
create_kiwoom_connector: 정상 생성, app_key/secret 없음

의존성: websockets, engine_state, ws_subscribe_control, engine_ws_reg, engine_ws,
  engine_symbol_utils, broker_factory, kiwoom_rest, core_queues
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


def _make_kiwoom_socket(uri="wss://test", token="tok", on_message=None, on_disconnect=None, queue_callback=None):
    """_KiwoomSocket 인스턴스 생성."""
    from backend.app.core.kiwoom_connector import _KiwoomSocket
    return _KiwoomSocket(
        uri=uri,
        token=token,
        on_message=on_message or AsyncMock(),
        on_disconnect=on_disconnect,
        queue_callback=queue_callback,
    )


def _make_kiwoom_connector(app_key="key", app_secret="secret", ws_uri="wss://test"):
    """KiwoomConnector 인스턴스 생성."""
    from backend.app.core.kiwoom_connector import KiwoomConnector
    return KiwoomConnector(app_key=app_key, app_secret=app_secret, ws_uri=ws_uri)


# ── _KiwoomSocket.__init__ ─────────────────────────────────────────────────────

class TestKiwoomSocketInit:
    def test_init_stores_params(self):
        on_msg = AsyncMock()
        on_disc = AsyncMock()
        q_cb = MagicMock()
        sock = _make_kiwoom_socket(uri="wss://x", token="t", on_message=on_msg, on_disconnect=on_disc, queue_callback=q_cb)
        assert sock._uri == "wss://x"
        assert sock._token == "t"
        assert sock._on_message is on_msg
        assert sock._on_disconnect is on_disc
        assert sock._queue_callback is q_cb
        assert sock.connected is False
        assert sock._ws is None
        assert sock._recv_task is None

    def test_init_defaults_on_disconnect_and_queue(self):
        sock = _make_kiwoom_socket()
        assert sock._on_disconnect is None
        assert sock._queue_callback is None


# ── _KiwoomSocket.connect ──────────────────────────────────────────────────────

class TestKiwoomSocketConnect:
    async def test_connect_success(self):
        mock_ws = _mock_ws_connection()
        mock_mod, _ = _mock_websockets_module()
        mock_mod.connect.return_value = mock_ws
        with patch("backend.app.core.kiwoom_connector.websockets", mock_mod):
            sock = _make_kiwoom_socket()
            with patch.object(sock, "_recv_loop", new_callable=AsyncMock):
                await sock.connect()
            assert sock.connected is True
            assert sock._ws is mock_ws
            mock_mod.connect.assert_called_once()
            # LOGIN 전송 확인
            sent_msg = mock_ws.send.call_args[0][0]
            parsed = json.loads(sent_msg)
            assert parsed["trnm"] == "LOGIN"
            assert parsed["token"] == "tok"

    async def test_connect_no_websockets_raises(self):
        with patch("backend.app.core.kiwoom_connector.websockets", None):
            sock = _make_kiwoom_socket()
            with pytest.raises(RuntimeError, match="websockets"):
                await sock.connect()

    async def test_connect_clears_stop_event(self):
        mock_ws = _mock_ws_connection()
        mock_mod, _ = _mock_websockets_module()
        mock_mod.connect.return_value = mock_ws
        with patch("backend.app.core.kiwoom_connector.websockets", mock_mod):
            sock = _make_kiwoom_socket()
            sock._stop_event.set()
            with patch.object(sock, "_recv_loop", new_callable=AsyncMock):
                await sock.connect()
            assert sock._stop_event.is_set() is False


# ── _KiwoomSocket.disconnect ───────────────────────────────────────────────────

class TestKiwoomSocketDisconnect:
    async def test_disconnect_normal(self):
        sock = _make_kiwoom_socket()
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
        sock = _make_kiwoom_socket()
        mock_task = MagicMock()
        mock_task.done.return_value = True
        sock._recv_task = mock_task
        await sock.disconnect()
        mock_task.cancel.assert_not_called()

    async def test_disconnect_ws_close_failure(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.close.side_effect = Exception("close fail")
        sock._ws = mock_ws
        sock.connected = True
        await sock.disconnect()
        assert sock._ws is None


# ── _KiwoomSocket.send ─────────────────────────────────────────────────────────

class TestKiwoomSocketSend:
    async def test_send_success(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        sock._ws = mock_ws
        sock.connected = True
        result = await sock.send({"trnm": "REG", "data": []})
        assert result is True
        mock_ws.send.assert_called_once()

    async def test_send_not_connected(self):
        sock = _make_kiwoom_socket()
        sock._ws = _mock_ws_connection()
        sock.connected = False
        result = await sock.send({"trnm": "REG"})
        assert result is False

    async def test_send_no_ws(self):
        sock = _make_kiwoom_socket()
        sock.connected = True
        sock._ws = None
        result = await sock.send({"trnm": "REG"})
        assert result is False


# ── _KiwoomSocket._recv_loop ───────────────────────────────────────────────────

class TestKiwoomSocketRecvLoop:
    async def test_string_ping_responded(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = ["PING", asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        mock_ws.send.assert_called_with("PING")

    async def test_json_ping_responded(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        ping_msg = json.dumps({"trnm": "PING"})
        mock_ws.recv.side_effect = [ping_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        mock_ws.send.assert_called_with(ping_msg)

    async def test_list_message_skipped(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = ["[1,2,3]", asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_not_called()

    async def test_login_success_calls_on_message(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        login_msg = json.dumps({"trnm": "LOGIN", "return_code": "0", "return_msg": "OK"})
        mock_ws.recv.side_effect = [login_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_called_once()
        called_msg = on_msg.call_args[0][0]
        assert called_msg["trnm"] == "LOGIN"

    async def test_login_failure_sets_connected_false(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        login_msg = json.dumps({"trnm": "LOGIN", "return_code": "1", "return_msg": "FAIL"})
        mock_ws.recv.side_effect = [login_msg]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        await sock._recv_loop()
        assert sock.connected is False
        on_msg.assert_not_called()

    async def test_real_message_uses_queue_callback(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        real_msg = json.dumps({"trnm": "REAL", "data": [{"code": "005930"}]})
        mock_ws.recv.side_effect = [real_msg, asyncio.CancelledError()]
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

    async def test_reg_message_calls_on_message(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        reg_msg = json.dumps({"trnm": "REG", "return_code": "0", "data": ["005930"]})
        mock_ws.recv.side_effect = [reg_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_called_once()

    async def test_system_message_warns_and_continues(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        sys_msg = json.dumps({"trnm": "SYSTEM", "msg": "shutdown"})
        mock_ws.recv.side_effect = [sys_msg, asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        # SYSTEM도 최종적으로 on_message 호출됨 (비-REAL 콜백)
        on_msg.assert_called_once()

    async def test_connection_closed_triggers_on_disconnect(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        _, closed_cls = _mock_websockets_module()
        mock_ws.recv.side_effect = closed_cls("closed")
        sock._ws = mock_ws
        sock.connected = True
        on_disc = AsyncMock()
        sock._on_disconnect = on_disc
        with patch("backend.app.core.kiwoom_connector._WsConnectionClosed", closed_cls):
            await sock._recv_loop()
        assert sock.connected is False
        on_disc.assert_called_once()

    async def test_connection_closed_no_on_disconnect(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        _, closed_cls = _mock_websockets_module()
        mock_ws.recv.side_effect = closed_cls("closed")
        sock._ws = mock_ws
        sock.connected = True
        sock._on_disconnect = None
        with patch("backend.app.core.kiwoom_connector._WsConnectionClosed", closed_cls):
            await sock._recv_loop()
        assert sock.connected is False

    async def test_non_connection_error_continues_loop(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = [ValueError("test error"), asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        with patch("backend.app.core.kiwoom_connector.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(asyncio.CancelledError):
                await sock._recv_loop()
        assert sock.connected is True

    async def test_json_decode_error_skipped(self):
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        mock_ws.recv.side_effect = ["not_json{{{", asyncio.CancelledError()]
        sock._ws = mock_ws
        sock.connected = True
        on_msg = AsyncMock()
        sock._on_message = on_msg
        with pytest.raises(asyncio.CancelledError):
            await sock._recv_loop()
        on_msg.assert_not_called()

    async def test_connection_closed_stop_event_set_no_disconnect(self):
        """stop_event가 recv 중 설정된 경우 on_disconnect 호출 안함."""
        sock = _make_kiwoom_socket()
        mock_ws = _mock_ws_connection()
        _, closed_cls = _mock_websockets_module()

        def _raise_and_set_stop(*args):
            sock._stop_event.set()
            raise closed_cls("closed")

        mock_ws.recv.side_effect = _raise_and_set_stop
        sock._ws = mock_ws
        sock.connected = True
        on_disc = AsyncMock()
        sock._on_disconnect = on_disc
        with patch("backend.app.core.kiwoom_connector._WsConnectionClosed", closed_cls):
            await sock._recv_loop()
        assert sock.connected is False
        on_disc.assert_not_called()


# ── KiwoomConnector.__init__ / properties ──────────────────────────────────────

class TestKiwoomConnectorInit:
    def test_init_stores_params(self):
        conn = _make_kiwoom_connector(app_key="k1", app_secret="s1", ws_uri="wss://x")
        assert conn._app_key == "k1"
        assert conn._app_secret == "s1"
        assert conn._ws_uri == "wss://x"
        assert conn._socket is None
        assert conn._token is None
        assert conn._connected is False
        assert conn._received_count == 0
        assert conn._reconnecting is False
        assert conn._stop_reconnect is False
        assert conn._ws_queue is None

    def test_broker_id(self):
        conn = _make_kiwoom_connector()
        assert conn.broker_id == "kiwoom"

    def test_is_connected_false_default(self):
        conn = _make_kiwoom_connector()
        assert conn.is_connected() is False

    def test_is_connected_true_when_socket_connected(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        assert conn.is_connected() is True

    def test_is_connected_false_when_socket_not_connected(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = False
        conn._socket = mock_socket
        assert conn.is_connected() is False

    def test_supports_ack(self):
        conn = _make_kiwoom_connector()
        assert conn.supports_ack() is True


# ── KiwoomConnector.connect ────────────────────────────────────────────────────

class TestKiwoomConnectorConnect:
    async def test_connect_success(self):
        conn = _make_kiwoom_connector()
        with (
            patch.object(conn, "_get_token_async", AsyncMock(return_value="tok123")),
            patch("backend.app.core.kiwoom_connector._KiwoomSocket") as mock_sock_cls,
            patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()),
        ):
            mock_socket = AsyncMock()
            mock_sock_cls.return_value = mock_socket
            await conn.connect()
            assert conn._connected is True
            assert conn._token == "tok123"
            mock_socket.connect.assert_called_once()

    async def test_connect_already_connected_returns(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        with (
            patch.object(conn, "_get_token_async", AsyncMock()) as mock_token,
            patch("backend.app.core.kiwoom_connector._KiwoomSocket") as mock_sock_cls,
        ):
            await conn.connect()
            mock_token.assert_not_called()
            mock_sock_cls.assert_not_called()

    async def test_connect_token_failure_raises(self):
        conn = _make_kiwoom_connector()
        with (
            patch.object(conn, "_get_token_async", AsyncMock(return_value=None)),
            patch("backend.app.core.kiwoom_connector._KiwoomSocket") as mock_sock_cls,
        ):
            with pytest.raises(ConnectionError, match="토큰"):
                await conn.connect()
            mock_sock_cls.assert_not_called()

    async def test_connect_socket_failure_triggers_reconnect(self):
        conn = _make_kiwoom_connector()
        with (
            patch.object(conn, "_get_token_async", AsyncMock(return_value="tok")),
            patch("backend.app.core.kiwoom_connector._KiwoomSocket") as mock_sock_cls,
            patch.object(conn, "_on_socket_disconnect", AsyncMock()),
        ):
            mock_socket = AsyncMock()
            mock_socket.connect.side_effect = Exception("ws fail")
            mock_sock_cls.return_value = mock_socket
            with pytest.raises(Exception, match="ws fail"):
                await conn.connect()
            assert conn._connected is False


# ── KiwoomConnector.disconnect ─────────────────────────────────────────────────

class TestKiwoomConnectorDisconnect:
    async def test_disconnect_normal(self):
        conn = _make_kiwoom_connector()
        mock_socket = AsyncMock()
        conn._socket = mock_socket
        conn._connected = True
        with patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()):
            await conn.disconnect()
        assert conn._connected is False
        assert conn._socket is None
        assert conn._stop_reconnect is True
        mock_socket.disconnect.assert_called_once()

    async def test_disconnect_no_socket(self):
        conn = _make_kiwoom_connector()
        conn._socket = None
        with patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()):
            await conn.disconnect()
        assert conn._connected is False
        assert conn._socket is None


# ── KiwoomConnector.send_message ───────────────────────────────────────────────

class TestKiwoomConnectorSendMessage:
    async def test_send_message_success(self):
        conn = _make_kiwoom_connector()
        mock_socket = AsyncMock()
        mock_socket.send.return_value = True
        conn._socket = mock_socket
        result = await conn.send_message({"trnm": "REG"})
        assert result is True
        mock_socket.send.assert_called_once()

    async def test_send_message_no_socket(self):
        conn = _make_kiwoom_connector()
        conn._socket = None
        result = await conn.send_message({"trnm": "REG"})
        assert result is False


# ── KiwoomConnector.subscribe / unsubscribe (compat) ───────────────────────────

class TestKiwoomConnectorSubscribeCompat:
    async def test_subscribe_delegates_to_subscribe_stocks(self):
        conn = _make_kiwoom_connector()
        with patch.object(conn, "subscribe_stocks", AsyncMock(return_value=True)) as mock_sub:
            result = await conn.subscribe("005930", ["0B"])
            mock_sub.assert_called_once_with(["005930"])
            assert result is True

    async def test_unsubscribe_delegates_to_unsubscribe_stocks(self):
        conn = _make_kiwoom_connector()
        with patch.object(conn, "unsubscribe_stocks", AsyncMock(return_value=True)) as mock_unsub:
            result = await conn.unsubscribe("005930", ["0B"])
            mock_unsub.assert_called_once_with(["005930"])
            assert result is True


# ── KiwoomConnector.subscribe_stocks ───────────────────────────────────────────

class TestKiwoomConnectorSubscribeStocks:
    async def test_subscribe_stocks_success(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_0b_reg_payloads", return_value=[{"trnm": "REG", "data": []}]),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(return_value=(True, "0"))) as mock_ack,
            patch("backend.app.services.engine_symbol_utils.get_ws_subscribe_code", side_effect=lambda cd: cd + "_AL"),
        ):
            result = await conn.subscribe_stocks(["005930"])
            assert result is True
            mock_ack.assert_called_once()

    async def test_subscribe_stocks_not_connected(self):
        conn = _make_kiwoom_connector()
        conn._connected = False
        result = await conn.subscribe_stocks(["005930"])
        assert result is False

    async def test_subscribe_stocks_multiple_payloads(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        payloads = [{"trnm": "REG", "data": ["005930"]}, {"trnm": "REG", "data": ["000660"]}]
        with (
            patch("backend.app.services.engine_ws_reg.build_0b_reg_payloads", return_value=payloads),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(return_value=(True, "0"))) as mock_ack,
            patch("backend.app.services.engine_symbol_utils.get_ws_subscribe_code", side_effect=lambda cd: cd + "_AL"),
        ):
            result = await conn.subscribe_stocks(["005930", "000660"])
            assert result is True
            assert mock_ack.call_count == 2

    async def test_subscribe_stocks_partial_failure(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        payloads = [{"trnm": "REG", "data": ["005930"]}, {"trnm": "REG", "data": ["000660"]}]
        with (
            patch("backend.app.services.engine_ws_reg.build_0b_reg_payloads", return_value=payloads),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(side_effect=[(True, "0"), (False, "1")])),
            patch("backend.app.services.engine_symbol_utils.get_ws_subscribe_code", side_effect=lambda cd: cd + "_AL"),
        ):
            result = await conn.subscribe_stocks(["005930", "000660"])
            assert result is False


# ── KiwoomConnector.unsubscribe_stocks ─────────────────────────────────────────

class TestKiwoomConnectorUnsubscribeStocks:
    async def test_unsubscribe_stocks_success(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_0b_remove_payloads", return_value=[{"trnm": "REMOVE", "data": []}]),
            patch("backend.app.services.engine_ws._ws_send_remove_fire_and_forget", AsyncMock(return_value=True)) as mock_ff,
            patch("backend.app.services.engine_symbol_utils.get_ws_subscribe_code", side_effect=lambda cd: cd + "_AL"),
        ):
            result = await conn.unsubscribe_stocks(["005930"])
            assert result is True
            mock_ff.assert_called_once()

    async def test_unsubscribe_stocks_not_connected(self):
        conn = _make_kiwoom_connector()
        conn._connected = False
        result = await conn.unsubscribe_stocks(["005930"])
        assert result is False

    async def test_unsubscribe_stocks_partial_failure(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        payloads = [{"trnm": "REMOVE", "data": ["005930"]}, {"trnm": "REMOVE", "data": ["000660"]}]
        with (
            patch("backend.app.services.engine_ws_reg.build_0b_remove_payloads", return_value=payloads),
            patch("backend.app.services.engine_ws._ws_send_remove_fire_and_forget", AsyncMock(side_effect=[True, False])),
            patch("backend.app.services.engine_symbol_utils.get_ws_subscribe_code", side_effect=lambda cd: cd + "_AL"),
        ):
            result = await conn.unsubscribe_stocks(["005930", "000660"])
            assert result is False


# ── KiwoomConnector.subscribe_dynamic / unsubscribe_dynamic ────────────────────

class TestKiwoomConnectorSubscribeDynamic:
    async def test_subscribe_dynamic_success(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_0d_reg_payloads", return_value=[{"trnm": "REG", "data": []}]),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(return_value=(True, "0"))) as mock_ack,
        ):
            await conn.subscribe_dynamic(["005930"])
            mock_ack.assert_called_once()

    async def test_subscribe_dynamic_not_connected(self):
        conn = _make_kiwoom_connector()
        conn._connected = False
        with (
            patch("backend.app.services.engine_ws_reg.build_0d_reg_payloads") as mock_build,
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack") as mock_ack,
        ):
            await conn.subscribe_dynamic(["005930"])
            mock_build.assert_not_called()
            mock_ack.assert_not_called()

    async def test_subscribe_dynamic_runtime_error_caught(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_0d_reg_payloads", return_value=[{"trnm": "REG"}]),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(side_effect=RuntimeError("no loop"))),
        ):
            # RuntimeError should be caught, not propagated
            await conn.subscribe_dynamic(["005930"])

    async def test_unsubscribe_dynamic_success(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_0d_remove_payloads", return_value=[{"trnm": "UNREG", "data": []}]),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(return_value=(True, "0"))) as mock_ack,
        ):
            await conn.unsubscribe_dynamic(["005930"])
            mock_ack.assert_called_once()

    async def test_unsubscribe_dynamic_not_connected(self):
        conn = _make_kiwoom_connector()
        conn._connected = False
        with (
            patch("backend.app.services.engine_ws_reg.build_0d_remove_payloads") as mock_build,
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack") as mock_ack,
        ):
            await conn.unsubscribe_dynamic(["005930"])
            mock_build.assert_not_called()
            mock_ack.assert_not_called()

    async def test_unsubscribe_dynamic_runtime_error_caught(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_0d_remove_payloads", return_value=[{"trnm": "UNREG"}]),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(side_effect=RuntimeError("no loop"))),
        ):
            await conn.unsubscribe_dynamic(["005930"])


# ── KiwoomConnector.subscribe_index ────────────────────────────────────────────

class TestKiwoomConnectorSubscribeIndex:
    async def test_subscribe_index_success(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_index_reg_payload", return_value={"trnm": "REG", "data": []}),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(return_value=(True, "0"))) as mock_ack,
        ):
            result = await conn.subscribe_index()
            assert result is True
            mock_ack.assert_called_once()

    async def test_subscribe_index_not_connected(self):
        conn = _make_kiwoom_connector()
        conn._connected = False
        result = await conn.subscribe_index()
        assert result is False

    async def test_subscribe_index_ack_failure(self):
        conn = _make_kiwoom_connector()
        conn._connected = True
        mock_socket = MagicMock()
        mock_socket.connected = True
        conn._socket = mock_socket
        with (
            patch("backend.app.services.engine_ws_reg.build_index_reg_payload", return_value={"trnm": "REG"}),
            patch("backend.app.services.engine_ws._ws_send_reg_unreg_and_wait_ack", AsyncMock(return_value=(False, ""))),
        ):
            result = await conn.subscribe_index()
            assert result is False


# ── KiwoomConnector._on_ws_message ─────────────────────────────────────────────

class TestKiwoomConnectorOnWsMessage:
    async def test_async_callback_awaited(self):
        conn = _make_kiwoom_connector()
        cb = AsyncMock()
        conn._receive_callback = cb
        await conn._on_ws_message({"trnm": "REAL"})
        assert conn._received_count == 1
        cb.assert_called_once_with({"trnm": "REAL"})

    async def test_sync_callback_called(self):
        conn = _make_kiwoom_connector()
        cb = MagicMock()
        conn._receive_callback = cb
        await conn._on_ws_message({"trnm": "REG"})
        assert conn._received_count == 1
        cb.assert_called_once_with({"trnm": "REG"})

    async def test_no_callback_no_error(self):
        conn = _make_kiwoom_connector()
        conn._receive_callback = None
        await conn._on_ws_message({"trnm": "REAL"})
        assert conn._received_count == 1


# ── KiwoomConnector._on_socket_disconnect ──────────────────────────────────────

class TestKiwoomConnectorOnSocketDisconnect:
    async def test_stop_reconnect_returns_immediately(self):
        conn = _make_kiwoom_connector()
        conn._stop_reconnect = True
        with (
            patch("backend.app.services.engine_state.state", MagicMock()),
            patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()),
            patch.object(conn, "_reconnect_loop", AsyncMock()) as mock_reconnect,
        ):
            await conn._on_socket_disconnect()
            mock_reconnect.assert_not_called()

    async def test_normal_triggers_reconnect(self):
        conn = _make_kiwoom_connector()
        conn._stop_reconnect = False
        with (
            patch("backend.app.services.engine_state.state", MagicMock()),
            patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()),
            patch.object(conn, "_reconnect_loop", AsyncMock()) as mock_reconnect,
        ):
            await conn._on_socket_disconnect()
            assert conn._connected is False
            assert conn._reconnecting is False
            mock_reconnect.assert_called_once()

    async def test_already_reconnecting_skips(self):
        conn = _make_kiwoom_connector()
        conn._reconnecting = True
        with (
            patch("backend.app.services.engine_state.state", MagicMock()),
            patch("backend.app.services.ws_subscribe_control.broadcast_ws_connection_status", MagicMock()),
            patch.object(conn, "_reconnect_loop", AsyncMock()) as mock_reconnect,
        ):
            await conn._on_socket_disconnect()
            mock_reconnect.assert_not_called()


# ── KiwoomConnector._reconnect_loop ────────────────────────────────────────────

class TestKiwoomConnectorReconnectLoop:
    async def test_stop_signal_immediately(self):
        conn = _make_kiwoom_connector()
        conn._stop_reconnect = True
        with patch("backend.app.core.kiwoom_connector.asyncio.sleep", new_callable=AsyncMock):
            await conn._reconnect_loop()

    async def test_token_failure_continues(self):
        conn = _make_kiwoom_connector()
        conn._stop_reconnect = False
        call_count = 0

        async def mock_sleep(*args):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                conn._stop_reconnect = True

        with (
            patch("backend.app.core.kiwoom_connector.asyncio.sleep", new=mock_sleep),
            patch.object(conn, "_get_token_async", AsyncMock(return_value=None)),
        ):
            await conn._reconnect_loop()


# ── KiwoomConnector.set_*_callback ─────────────────────────────────────────────

class TestKiwoomConnectorCallbacks:
    def test_set_reconnect_success_callback(self):
        conn = _make_kiwoom_connector()
        cb = MagicMock()
        conn.set_reconnect_success_callback(cb)
        assert conn._on_reconnect_success is cb

    def test_set_message_callback(self):
        conn = _make_kiwoom_connector()
        cb = MagicMock()
        conn.set_message_callback(cb)
        assert conn._receive_callback is cb

    def test_set_queue_callback(self):
        conn = _make_kiwoom_connector()
        q = asyncio.Queue()
        conn.set_queue_callback(q)
        assert conn._ws_queue is q


# ── KiwoomConnector._format_code ───────────────────────────────────────────────

class TestKiwoomConnectorFormatCode:
    def test_format_6digit_numeric(self):
        conn = _make_kiwoom_connector()
        result = conn._format_code("005930")
        assert result == "005930_AL"

    def test_format_6digit_alpha(self):
        conn = _make_kiwoom_connector()
        result = conn._format_code("0017J0")
        assert result == "0017J0_AL"

    def test_format_strips_a_prefix(self):
        conn = _make_kiwoom_connector()
        result = conn._format_code("A005930")
        assert result == "005930_AL"

    def test_format_non_6digit_passthrough(self):
        conn = _make_kiwoom_connector()
        result = conn._format_code("123")
        assert result == "123"

    def test_format_already_has_al_suffix(self):
        conn = _make_kiwoom_connector()
        result = conn._format_code("005930_AL")
        assert result == "005930_AL"

    def test_format_uppercase(self):
        conn = _make_kiwoom_connector()
        result = conn._format_code("a005930")
        assert result == "005930_AL"


# ── KiwoomConnector._get_token_async ───────────────────────────────────────────

class TestKiwoomConnectorGetToken:
    async def test_reuse_broker_rest_apis(self):
        conn = _make_kiwoom_connector()
        mock_state = MagicMock()
        mock_rest = AsyncMock()
        mock_rest.get_access_token = AsyncMock(return_value="tok123")
        mock_state.broker_rest_apis = {"kiwoom": mock_rest}
        with patch("backend.app.services.engine_state.state", mock_state):
            result = await conn._get_token_async()
        assert result == "tok123"

    async def test_auth_cache_fallback(self):
        conn = _make_kiwoom_connector()
        mock_state = MagicMock()
        mock_state.broker_rest_apis = {}
        mock_router = MagicMock()
        mock_auth = MagicMock()
        mock_rest = AsyncMock()
        mock_rest.get_access_token = AsyncMock(return_value="tok456")
        mock_auth.rest_api = mock_rest
        mock_router._auth_cache = {"kiwoom": mock_auth}
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_factory.get_router", MagicMock(return_value=mock_router)),
        ):
            result = await conn._get_token_async()
        assert result == "tok456"

    async def test_new_kiwoom_rest_fallback(self):
        conn = _make_kiwoom_connector()
        mock_state = MagicMock()
        mock_state.broker_rest_apis = {}
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_factory.get_router", MagicMock(side_effect=Exception("no router"))),
            patch("backend.app.core.kiwoom_rest.KiwoomRestAPI") as mock_cls,
        ):
            mock_api = AsyncMock()
            mock_api.get_access_token = AsyncMock(return_value="tok789")
            mock_cls.return_value = mock_api
            result = await conn._get_token_async()
        assert result == "tok789"

    async def test_all_paths_fail_returns_none(self):
        conn = _make_kiwoom_connector()
        mock_state = MagicMock()
        mock_state.broker_rest_apis = {}
        with (
            patch("backend.app.services.engine_state.state", mock_state),
            patch("backend.app.core.broker_factory.get_router", MagicMock(side_effect=Exception("no router"))),
            patch("backend.app.core.kiwoom_rest.KiwoomRestAPI") as mock_cls,
        ):
            mock_api = AsyncMock()
            mock_api.get_access_token = AsyncMock(return_value=None)
            mock_cls.return_value = mock_api
            result = await conn._get_token_async()
        assert result is None


# ── create_kiwoom_connector ────────────────────────────────────────────────────

class TestCreateKiwoomConnector:
    def test_create_success(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {
            "kiwoom_app_key": "mykey",
            "kiwoom_app_secret": "mysecret",
        }
        with patch("backend.app.services.engine_state.state", mock_state):
            from backend.app.core.kiwoom_connector import create_kiwoom_connector
            conn = create_kiwoom_connector()
            assert conn._app_key == "mykey"
            assert conn._app_secret == "mysecret"

    def test_create_no_credentials_raises(self):
        mock_state = MagicMock()
        mock_state.integrated_system_settings_cache = {}
        with patch("backend.app.services.engine_state.state", mock_state):
            from backend.app.core.kiwoom_connector import create_kiwoom_connector
            with pytest.raises(ValueError, match="app_key"):
                create_kiwoom_connector()
