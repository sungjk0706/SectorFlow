"""WebSocket 매니저 단위 테스트 — ws_manager.py.

_encode_realdata 모듈 함수 + WSManager 클래스 메서드 전체 검증.
mock WebSocket (MagicMock + AsyncMock)으로 연결/해제/브로드캐스트 흐름 테스트.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

# Initialize queues before any lazy import of pipeline_compute (module-level get_broadcast_queue call)
from backend.app.services.core_queues import initialize_queues
initialize_queues()


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_ws() -> MagicMock:
    """mock WebSocket — send_text/send_bytes/close AsyncMock."""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.close = AsyncMock()
    ws.accept = AsyncMock()
    return ws


# ── _encode_realdata ───────────────────────────────────────────────────────────

class TestEncodeRealdata:
    """_encode_realdata: FID 필터링 + key shortening + LRU 캐시."""

    def setup_method(self):
        from backend.app.web.ws_manager import _encoding_cache
        _encoding_cache.clear()

    def test_fid_filtering_default(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": {"10": "70000", "11": "500", "99": "x"}}
        text, binary = _encode_realdata(data)
        parsed = json.loads(text)
        values = parsed["data"]["v"]
        assert "10" in values
        assert "11" in values
        assert "99" not in values  # ALLOWED_FIDS에 없는 FID 제거

    def test_fid_filtering_custom_fids(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": {"10": "70000", "12": "100", "14": "200"}}
        custom = frozenset({"10", "14"})
        text, _ = _encode_realdata(data, subscribed_fids=custom)
        parsed = json.loads(text)
        values = parsed["data"]["v"]
        assert "10" in values
        assert "14" in values
        assert "12" not in values

    def test_key_shortening(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        text, _ = _encode_realdata(data)
        parsed = json.loads(text)
        assert parsed["event"] == "real-data"
        assert parsed["data"]["t"] == "real"
        assert parsed["data"]["i"] == "005930"
        assert parsed["data"]["v"] == {"10": "70000"}

    def test_v_stamp_added(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        text, _ = _encode_realdata(data)
        parsed = json.loads(text)
        assert parsed["data"]["_v"] == 1

    def test_v_stamp_preserved(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}, "_v": 2}
        text, _ = _encode_realdata(data)
        parsed = json.loads(text)
        assert parsed["data"]["_v"] == 2

    def test_cache_hit(self):
        from backend.app.web.ws_manager import _encode_realdata, _encoding_cache
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        text1, _ = _encode_realdata(data)
        text2, _ = _encode_realdata(data)
        assert text1 == text2
        assert len(_encoding_cache) == 1

    def test_cache_miss_different_data(self):
        from backend.app.web.ws_manager import _encode_realdata, _encoding_cache
        data1 = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        data2 = {"type": "real", "item": "005930", "values": {"10": "71000"}}
        _encode_realdata(data1)
        _encode_realdata(data2)
        assert len(_encoding_cache) == 2

    def test_cache_miss_different_fids(self):
        from backend.app.web.ws_manager import _encode_realdata, _encoding_cache
        data = {"type": "real", "item": "005930", "values": {"10": "70000", "12": "100"}}
        _encode_realdata(data, subscribed_fids=frozenset({"10"}))
        _encode_realdata(data, subscribed_fids=frozenset({"12"}))
        assert len(_encoding_cache) == 2

    def test_cache_lru_eviction(self):
        from backend.app.web.ws_manager import (
            _encode_realdata, _encoding_cache, _ENCODING_CACHE_MAX_SIZE,
        )
        # 캐시 최대 크기까지 채운 후 1개 추가 → 가장 오래된 것 제거
        for i in range(_ENCODING_CACHE_MAX_SIZE + 1):
            data = {"type": "real", "item": f"00593{i:02d}", "values": {"10": str(70000 + i)}}
            _encode_realdata(data)
        assert len(_encoding_cache) == _ENCODING_CACHE_MAX_SIZE

    def test_values_not_dict_passthrough(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": "not_a_dict"}
        text, _ = _encode_realdata(data)
        parsed = json.loads(text)
        assert parsed["data"]["v"] == "not_a_dict"

    def test_values_missing(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930"}
        text, _ = _encode_realdata(data)
        parsed = json.loads(text)
        assert "v" not in parsed["data"] or parsed["data"].get("v") is None

    def test_non_shortened_key_preserved(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}, "extra": "keep"}
        text, _ = _encode_realdata(data)
        parsed = json.loads(text)
        assert parsed["data"]["extra"] == "keep"

    def test_binary_frame_is_none(self):
        from backend.app.web.ws_manager import _encode_realdata
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        _, binary = _encode_realdata(data)
        assert binary is None


# ── WSManager 초기 상태 ────────────────────────────────────────────────────────

class TestWSManagerInit:
    """WSManager __init__ — 초기 상태 검증."""

    def test_init_empty_clients(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        assert len(mgr._clients) == 0
        assert mgr._client_active_page == {}
        assert mgr._client_subscribed_fids == {}
        assert mgr._shutdown_timer is None

    def test_client_count_zero(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        assert mgr.client_count == 0


# ── register / unregister ──────────────────────────────────────────────────────

class TestRegisterUnregister:
    """WSManager register / unregister."""

    async def test_register_adds_client(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        with patch.object(mgr, "_send_initial_data_on_connect", AsyncMock()):
            await mgr.register(ws)
        assert ws in mgr._clients
        assert mgr.client_count == 1

    async def test_register_cancels_shutdown_timer(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        mock_timer = MagicMock()
        mock_timer.cancel = MagicMock()
        mgr._shutdown_timer = mock_timer
        ws = _make_ws()
        with patch.object(mgr, "_send_initial_data_on_connect", AsyncMock()):
            await mgr.register(ws)
        mock_timer.cancel.assert_called_once()
        assert mgr._shutdown_timer is None

    async def test_register_no_timer_no_cancel(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        with patch.object(mgr, "_send_initial_data_on_connect", AsyncMock()):
            await mgr.register(ws)
        assert mgr._shutdown_timer is None

    async def test_register_calls_initial_data(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mock_init = AsyncMock()
        with patch.object(mgr, "_send_initial_data_on_connect", mock_init):
            await mgr.register(ws)
        mock_init.assert_awaited_once_with(ws)

    def test_unregister_removes_client(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients.add(ws)
        mgr.unregister(ws)
        assert ws not in mgr._clients
        assert mgr.client_count == 0

    def test_unregister_clears_active_page(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients.add(ws)
        mgr._client_active_page[ws] = "buy-target"
        mgr.unregister(ws)
        assert ws not in mgr._client_active_page

    def test_unregister_clears_subscribed_fids(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients.add(ws)
        mgr._client_subscribed_fids[ws] = frozenset({"10"})
        mgr.unregister(ws)
        assert ws not in mgr._client_subscribed_fids

    def test_unregister_idempotent(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr.unregister(ws)  # 없는 클라이언트 제거 — 에러 없음
        assert mgr.client_count == 0

    def test_unregister_schedules_shutdown_when_empty(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients.add(ws)
        mock_loop = MagicMock()
        mock_timer = MagicMock()
        mock_loop.call_later = MagicMock(return_value=mock_timer)
        with patch("backend.app.web.ws_manager.asyncio.get_running_loop", return_value=mock_loop):
            mgr.unregister(ws)
        mock_loop.call_later.assert_called_once()
        assert mgr._shutdown_timer is mock_timer

    def test_unregister_no_shutdown_when_clients_remain(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2 = _make_ws(), _make_ws()
        mgr._clients.add(ws1)
        mgr._clients.add(ws2)
        mgr.unregister(ws1)
        assert mgr._shutdown_timer is None

    def test_unregister_runtime_error_no_loop(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients.add(ws)
        with patch("backend.app.web.ws_manager.asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            mgr.unregister(ws)
        assert mgr._shutdown_timer is None

    def test_unregister_no_double_timer(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients.add(ws)
        existing_timer = MagicMock()
        mgr._shutdown_timer = existing_timer
        mock_loop = MagicMock()
        with patch("backend.app.web.ws_manager.asyncio.get_running_loop", return_value=mock_loop):
            mgr.unregister(ws)
        # 이미 타이머가 있으면 새로 예약하지 않음
        mock_loop.call_later.assert_not_called()


# ── active page 관리 ──────────────────────────────────────────────────────────

class TestActivePage:
    """WSManager set/clear_active_page, get_active_pages."""

    def test_set_active_page(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr.set_active_page(ws, "buy-target")
        assert mgr._client_active_page[ws] == "buy-target"

    def test_clear_active_page(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._client_active_page[ws] = "sell-position"
        mgr.clear_active_page(ws)
        assert ws not in mgr._client_active_page

    def test_clear_active_page_not_set(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr.clear_active_page(ws)  # 없어도 에러 없음
        assert ws not in mgr._client_active_page

    def test_get_active_pages(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2, ws3 = _make_ws(), _make_ws(), _make_ws()
        mgr._client_active_page = {ws1: "buy-target", ws2: "sell-position", ws3: "buy-target"}
        pages = mgr.get_active_pages()
        assert pages == {"buy-target", "sell-position"}

    def test_get_active_pages_empty(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        assert mgr.get_active_pages() == set()


# ── subscribed FID 관리 ────────────────────────────────────────────────────────

class TestSubscribedFids:
    """WSManager set/clear_subscribed_fids."""

    def test_set_subscribed_fids(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr.set_subscribed_fids(ws, ["10", "11"])
        assert mgr._client_subscribed_fids[ws] == frozenset({"10", "11"})

    def test_clear_subscribed_fids(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._client_subscribed_fids[ws] = frozenset({"10"})
        mgr.clear_subscribed_fids(ws)
        assert ws not in mgr._client_subscribed_fids

    def test_clear_subscribed_fids_not_set(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr.clear_subscribed_fids(ws)  # 없어도 에러 없음
        assert ws not in mgr._client_subscribed_fids


# ── _stamp ─────────────────────────────────────────────────────────────────────

class TestStamp:
    """WSManager._stamp — 스키마 버전 자동 삽입."""

    def test_stamp_adds_v(self):
        from backend.app.web.ws_manager import WSManager
        data = {"foo": "bar"}
        result = WSManager._stamp(data)
        assert result["_v"] == 1

    def test_stamp_preserves_existing_v(self):
        from backend.app.web.ws_manager import WSManager
        data = {"foo": "bar", "_v": 2}
        result = WSManager._stamp(data)
        assert result["_v"] == 2

    def test_stamp_mutates_in_place(self):
        from backend.app.web.ws_manager import WSManager
        data = {"foo": "bar"}
        result = WSManager._stamp(data)
        assert result is data  # 같은 객체 반환


# ── _send_broadcast ────────────────────────────────────────────────────────────

class TestSendBroadcast:
    """WSManager._send_broadcast — 모든 클라이언트 즉시 전송."""

    async def test_broadcast_to_all_clients(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2 = _make_ws(), _make_ws()
        mgr._clients = {ws1, ws2}
        await mgr._send_broadcast("sector-scores", {"data": 1})
        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()
        msg = json.loads(ws1.send_text.call_args[0][0])
        assert msg["event"] == "sector-scores"
        assert msg["data"]["_v"] == 1

    async def test_broadcast_removes_dead_clients(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2 = _make_ws(), _make_ws()
        ws1.send_text = AsyncMock(side_effect=Exception("disconnected"))
        mgr._clients = {ws1, ws2}
        await mgr._send_broadcast("test", {"data": 1})
        assert ws1 not in mgr._clients
        assert ws2 in mgr._clients

    async def test_broadcast_empty_clients(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        await mgr._send_broadcast("test", {"data": 1})  # 에러 없음


# ── _send_realdata_immediate ──────────────────────────────────────────────────

class TestSendRealdataImmediate:
    """WSManager._send_realdata_immediate — 텍스트 즉시 전송."""

    async def test_send_to_all(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2 = _make_ws(), _make_ws()
        mgr._clients = {ws1, ws2}
        await mgr._send_realdata_immediate('{"event":"real-data"}')
        ws1.send_text.assert_awaited_once_with('{"event":"real-data"}')
        ws2.send_text.assert_awaited_once_with('{"event":"real-data"}')

    async def test_removes_dead(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        ws.send_text = AsyncMock(side_effect=Exception("dead"))
        mgr._clients = {ws}
        await mgr._send_realdata_immediate("text")
        assert ws not in mgr._clients


# ── _send_realdata_encoded ─────────────────────────────────────────────────────

class TestSendRealdataEncoded:
    """WSManager._send_realdata_encoded — FID 그룹화 전송."""

    def setup_method(self):
        from backend.app.web.ws_manager import _encoding_cache
        _encoding_cache.clear()

    async def test_group_by_fids(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2 = _make_ws(), _make_ws()
        mgr._clients = {ws1, ws2}
        mgr._client_subscribed_fids[ws1] = frozenset({"10"})
        mgr._client_subscribed_fids[ws2] = frozenset({"10", "11"})
        data = {"type": "real", "item": "005930", "values": {"10": "70000", "11": "500"}}
        await mgr._send_realdata_encoded(data, "005930")
        # ws1은 FID 10만, ws2는 FID 10,11 — 서로 다른 페이로드
        msg1 = json.loads(ws1.send_text.call_args[0][0])
        msg2 = json.loads(ws2.send_text.call_args[0][0])
        assert "10" in msg1["data"]["v"]
        assert "11" not in msg1["data"]["v"]
        assert "10" in msg2["data"]["v"]
        assert "11" in msg2["data"]["v"]

    async def test_default_fids_for_unset(self):
        from backend.app.web.ws_manager import WSManager, ALLOWED_FIDS
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        # subscribed_fids 미설정 → ALLOWED_FIDS 사용
        data = {"type": "real", "item": "005930", "values": {fid: "x" for fid in ALLOWED_FIDS}}
        await mgr._send_realdata_encoded(data, "005930")
        ws.send_text.assert_awaited_once()

    async def test_removes_dead(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        ws.send_text = AsyncMock(side_effect=Exception("dead"))
        mgr._clients = {ws}
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        await mgr._send_realdata_encoded(data, "005930")
        assert ws not in mgr._clients

    async def test_empty_clients(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        await mgr._send_realdata_encoded(data, "005930")  # 에러 없음


# ── broadcast_to_pages ─────────────────────────────────────────────────────────

class TestBroadcastToPages:
    """WSManager.broadcast_to_pages — 페이지 필터링 전송."""

    async def test_send_to_matching_pages(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2 = _make_ws(), _make_ws()
        mgr._clients = {ws1, ws2}
        mgr._client_active_page[ws1] = "buy-target"
        mgr._client_active_page[ws2] = "sell-position"
        await mgr.broadcast_to_pages("event", {"data": 1}, {"buy-target"})
        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_not_awaited()

    async def test_no_clients_returns(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        await mgr.broadcast_to_pages("event", {"data": 1}, {"buy-target"})  # 에러 없음

    async def test_empty_pages_returns(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mgr._client_active_page[ws] = "buy-target"
        await mgr.broadcast_to_pages("event", {"data": 1}, set())
        ws.send_text.assert_not_awaited()

    async def test_no_matching_clients(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mgr._client_active_page[ws] = "sell-position"
        await mgr.broadcast_to_pages("event", {"data": 1}, {"buy-target"})
        ws.send_text.assert_not_awaited()

    async def test_removes_dead(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        ws.send_text = AsyncMock(side_effect=Exception("dead"))
        mgr._clients = {ws}
        mgr._client_active_page[ws] = "buy-target"
        await mgr.broadcast_to_pages("event", {"data": 1}, {"buy-target"})
        assert ws not in mgr._clients


# ── broadcast ──────────────────────────────────────────────────────────────────

class TestBroadcast:
    """WSManager.broadcast — real-data 분기 / 일반 이벤트."""

    async def test_real_data_routes_to_encoded(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            with patch.object(mgr, "_send_realdata_encoded", AsyncMock()) as mock_enc:
                await mgr.broadcast("real-data", data)
        mock_enc.assert_awaited_once()

    async def test_real_data_empty_item(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        data = {"type": "real", "item": "", "values": {"10": "70000"}}
        with patch.object(mgr, "_send_realdata_encoded", AsyncMock()) as mock_enc:
            await mgr.broadcast("real-data", data)
        mock_enc.assert_awaited_once()

    async def test_non_real_data_routes_to_broadcast(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        with patch.object(mgr, "_send_broadcast", AsyncMock()) as mock_bc:
            await mgr.broadcast("sector-scores", {"data": 1})
        mock_bc.assert_awaited_once()

    async def test_no_clients_returns(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        await mgr.broadcast("sector-scores", {"data": 1})  # 에러 없음


# ── broadcast_threadsafe ───────────────────────────────────────────────────────

class TestBroadcastThreadsafe:
    """WSManager.broadcast_threadsafe — 스레드 안전 브로드캐스트."""

    def test_calls_run_coroutine_threadsafe(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mock_loop = MagicMock()
        with patch("backend.app.web.ws_manager.asyncio.run_coroutine_threadsafe",
                   side_effect=lambda coro, loop: coro.close()) as mock_rcs:
            mgr.broadcast_threadsafe("event", {"data": 1}, mock_loop)
        mock_rcs.assert_called_once()

    def test_no_clients_returns(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        mock_loop = MagicMock()
        with patch("backend.app.web.ws_manager.asyncio.run_coroutine_threadsafe") as mock_rcs:
            mgr.broadcast_threadsafe("event", {"data": 1}, mock_loop)
        mock_rcs.assert_not_called()


# ── send_to ────────────────────────────────────────────────────────────────────

class TestSendTo:
    """WSManager.send_to — 단일 클라이언트 유니캐스트."""

    async def test_send_success(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        await mgr.send_to(ws, "initial-snapshot", {"data": 1})
        ws.send_text.assert_awaited_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["event"] == "initial-snapshot"
        assert msg["data"]["_v"] == 1

    async def test_send_failure_removes_client(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        ws.send_text = AsyncMock(side_effect=Exception("send failed"))
        mgr._clients = {ws}
        await mgr.send_to(ws, "event", {"data": 1})
        assert ws not in mgr._clients


# ── _send ──────────────────────────────────────────────────────────────────────

class TestSend:
    """WSManager._send — 단일 전송, 실패 시 제거."""

    async def test_send_success(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        await mgr._send(ws, "text")
        ws.send_text.assert_awaited_once_with("text")

    async def test_send_failure_removes(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        ws.send_text = AsyncMock(side_effect=Exception("dead"))
        mgr._clients = {ws}
        await mgr._send(ws, "text")
        assert ws not in mgr._clients


# ── _send_sigterm ──────────────────────────────────────────────────────────────

class TestSendSigterm:
    """WSManager._send_sigterm — 전체 끊김 후 SIGTERM."""

    def test_clients_present_no_sigterm(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        with patch("os.kill") as mock_kill:
            mgr._send_sigterm()
        mock_kill.assert_not_called()
        assert mgr._shutdown_timer is None

    def test_no_clients_sends_sigterm(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        mgr._clients = set()
        with patch("os.kill") as mock_kill:
            with patch("backend.app.services.engine_state.state") as mock_state:
                mock_state.shutdown_requested = False
                mock_state.connector_manager = None
                mgr._send_sigterm()
        mock_kill.assert_called_once()

    def test_shutdown_requested_no_sigterm(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        mgr._clients = set()
        with patch("os.kill") as mock_kill:
            with patch("backend.app.services.engine_state.state") as mock_state:
                mock_state.shutdown_requested = True
                mock_state.connector_manager = None
                mgr._send_sigterm()
        mock_kill.assert_not_called()

    def test_broker_reconnecting_no_sigterm(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        mgr._clients = set()
        mock_cm = MagicMock()
        mock_cm.is_connected = MagicMock(return_value=False)
        with patch("os.kill") as mock_kill:
            with patch("backend.app.services.engine_state.state") as mock_state:
                mock_state.shutdown_requested = False
                mock_state.connector_manager = mock_cm
                mgr._send_sigterm()
        mock_kill.assert_not_called()
        assert mgr._shutdown_timer is None


# ── close_all ──────────────────────────────────────────────────────────────────

class TestCloseAll:
    """WSManager.close_all — 전체 종료."""

    async def test_close_all_clients(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1, ws2 = _make_ws(), _make_ws()
        mgr._clients = {ws1, ws2}
        await mgr.close_all()
        ws1.close.assert_awaited_once()
        ws2.close.assert_awaited_once()
        assert len(mgr._clients) == 0

    async def test_close_all_cancels_timer(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        mock_timer = MagicMock()
        mgr._shutdown_timer = mock_timer
        await mgr.close_all()
        mock_timer.cancel.assert_called_once()
        assert mgr._shutdown_timer is None

    async def test_close_all_no_timer(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        await mgr.close_all()  # 타이머 없어도 에러 없음
        assert mgr._shutdown_timer is None

    async def test_close_all_client_exception(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        ws.close = AsyncMock(side_effect=Exception("close failed"))
        mgr._clients = {ws}
        await mgr.close_all()  # 예외 무시
        assert len(mgr._clients) == 0


# ── _send_initial_data_on_connect ─────────────────────────────────────────────

class TestSendInitialData:
    """WSManager._send_initial_data_on_connect — 연결 시 초기 데이터."""

    async def test_sends_buy_targets(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mock_targets = [{"code": "005930", "name": "삼성전자"}]
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   AsyncMock(return_value=mock_targets)):
            await mgr._send_initial_data_on_connect(ws)
        ws.send_text.assert_awaited_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["event"] == "buy-targets-update"
        assert msg["data"]["buy_targets"] == mock_targets

    async def test_no_targets_no_send(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   AsyncMock(return_value=[])):
            await mgr._send_initial_data_on_connect(ws)
        ws.send_text.assert_not_awaited()

    async def test_exception_no_raise(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        with patch("backend.app.services.sector_data_provider.get_buy_targets_sector_stocks",
                   AsyncMock(side_effect=Exception("db error"))):
            await mgr._send_initial_data_on_connect(ws)  # 예외 전파 없음
        ws.send_text.assert_not_awaited()


# ── client_count ───────────────────────────────────────────────────────────────

class TestClientCount:
    """WSManager.client_count 프로퍼티."""

    def test_zero(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        assert mgr.client_count == 0

    def test_multiple(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        mgr._clients = {_make_ws(), _make_ws(), _make_ws()}
        assert mgr.client_count == 3
