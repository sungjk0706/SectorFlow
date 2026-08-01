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
    """WSManager set_subscribed_fids."""

    def test_set_subscribed_fids(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr.set_subscribed_fids(ws, ["10", "11"])
        assert mgr._client_subscribed_fids[ws] == frozenset({"10", "11"})


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
    """WSManager.broadcast — real-data 분기 / 일반 이벤트.

    마스터 캐시 구독 모델: real-data는 해당 종목을 구독 중인 클라이언트에게만 전송.
    """

    async def test_real_data_routes_to_encoded(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        # 종목 구독 설정 (마스터 캐시 구독 모델)
        mgr._symbol_subscribers["005930"] = {ws}
        mgr._client_subscribed_codes[ws] = {"005930"}
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            with patch.object(mgr, "_send_realdata_encoded", AsyncMock()) as mock_enc:
                await mgr.broadcast("real-data", data)
        mock_enc.assert_awaited_once()

    async def test_real_data_no_subscribers_skipped(self):
        """구독자가 없으면 real-data 전송 생략 (페이지별 구독 push 모델)."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        data = {"type": "real", "item": "005930", "values": {"10": "70000"}}
        with patch("backend.app.services.engine_symbol_utils._base_stk_cd", return_value="005930"):
            with patch.object(mgr, "_send_realdata_encoded", AsyncMock()) as mock_enc:
                await mgr.broadcast("real-data", data)
        mock_enc.assert_not_awaited()

    async def test_real_data_empty_item(self):
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        data = {"type": "real", "item": "", "values": {"10": "70000"}}
        with patch.object(mgr, "_send_realdata_encoded", AsyncMock()) as mock_enc:
            await mgr.broadcast("real-data", data)
        mock_enc.assert_not_awaited()  # 빈 code → 구독자 없음 → 전송 생략

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


# ── 종목별 구독 관리 (마스터 캐시 단일 시세 소스 — 설계 결정 2) ──────────────────

class TestSubscribeCodes:
    """WSManager.subscribe_codes / _cleanup_subscribed_codes — 종목별 구독 참조 카운트 맵."""

    def test_subscribe_codes_adds_subscriber(self):
        """subscribe_codes — 클라이언트가 종목 구독 시 _symbol_subscribers에 추가."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mgr.subscribe_codes(ws, "sell-position", ["005930", "000660"])
        assert mgr._symbol_subscribers["005930"] == {ws}
        assert mgr._symbol_subscribers["000660"] == {ws}
        assert mgr._client_subscribed_codes[ws] == {"005930", "000660"}

    def test_subscribe_codes_returns_newly_subscribed(self):
        """0→1 전환 종목 집합 반환 — snapshot 전송용."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        newly = mgr.subscribe_codes(ws, "sell-position", ["005930", "000660"])
        assert newly == {"005930", "000660"}

    def test_subscribe_codes_second_client_no_newly_for_shared_code(self):
        """두 번째 클라이언트가 같은 종목 구독 시 newly_subscribed에서 제외 (이미 0→1 전환됨)."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws1 = _make_ws()
        ws2 = _make_ws()
        mgr._clients = {ws1, ws2}
        mgr.subscribe_codes(ws1, "sell-position", ["005930"])
        newly2 = mgr.subscribe_codes(ws2, "buy-target", ["005930"])
        # 005930은 이미 ws1이 구독 중이므로 0→1 전환 아님
        assert newly2 == set()
        assert mgr._symbol_subscribers["005930"] == {ws1, ws2}

    def test_subscribe_codes_replaces_previous_subscription(self):
        """페이지 전환 시 기존 구독 해제 후 새 코드로 교체."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mgr.subscribe_codes(ws, "sell-position", ["005930", "000660"])
        # 페이지 전환 — 000660 구독 해제, 035420 추가
        mgr.subscribe_codes(ws, "buy-target", ["005930", "035420"])
        assert mgr._symbol_subscribers["005930"] == {ws}
        assert "000660" not in mgr._symbol_subscribers  # 1→0 전환으로 제거
        assert mgr._symbol_subscribers["035420"] == {ws}
        assert mgr._client_subscribed_codes[ws] == {"005930", "035420"}

    def test_clear_active_page_unsubscribes_codes(self):
        """page-inactive 시 클라이언트의 종목 구독 전부 해제."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mgr.subscribe_codes(ws, "sell-position", ["005930", "000660"])
        mgr.clear_active_page(ws)
        assert "005930" not in mgr._symbol_subscribers
        assert "000660" not in mgr._symbol_subscribers
        assert ws not in mgr._client_subscribed_codes

    def test_unregister_cleans_up_subscriptions(self):
        """연결 해제 시 종목 구독 정리."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mgr.subscribe_codes(ws, "sell-position", ["005930"])
        mgr.unregister(ws)
        assert "005930" not in mgr._symbol_subscribers
        assert ws not in mgr._client_subscribed_codes

    def test_get_subscribers_for_code(self):
        """특정 종목을 구독 중인 클라이언트 집합 반환."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        mgr.subscribe_codes(ws, "sell-position", ["005930"])
        assert mgr.get_subscribers_for_code("005930") == {ws}
        assert mgr.get_subscribers_for_code("999999") == set()  # 미구독 종목

    def test_subscribe_codes_empty_codes_no_op(self):
        """빈 codes 리스트 시 구독 변경 없음."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        newly = mgr.subscribe_codes(ws, "sell-position", [])
        assert newly == set()
        assert mgr._client_subscribed_codes[ws] == set()


class TestBroadcastToCodeSubscribers:
    """WSManager.broadcast_to_code_subscribers — 구독자에게만 전송."""

    async def test_sends_to_subscribers_only(self):
        """구독 중인 클라이언트에게만 전송, 비구독 클라이언트 제외."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws_sub = _make_ws()
        ws_other = _make_ws()
        mgr._clients = {ws_sub, ws_other}
        mgr.subscribe_codes(ws_sub, "sell-position", ["005930"])
        await mgr.broadcast_to_code_subscribers("master-cache-delta", {"code": "005930"}, "005930")
        ws_sub.send_text.assert_awaited_once()
        ws_other.send_text.assert_not_awaited()

    async def test_no_subscribers_no_send(self):
        """구독자가 없으면 전송 생략."""
        from backend.app.web.ws_manager import WSManager
        mgr = WSManager()
        ws = _make_ws()
        mgr._clients = {ws}
        await mgr.broadcast_to_code_subscribers("master-cache-delta", {"code": "005930"}, "005930")
        ws.send_text.assert_not_awaited()
