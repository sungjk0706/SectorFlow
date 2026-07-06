# -*- coding: utf-8 -*-
"""WebSocket 클라이언트 연결 관리 — 즉시 broadcast.

set[WebSocket] 기반 직접 참조.
broadcast()는 async 함수로, 모든 이벤트를 await 기반 직접 전송한다.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any
from collections import OrderedDict
from fastapi import WebSocket
logger = logging.getLogger(__name__)

# real-data FID 필터: 프론트엔드에서 사용하는 FID만 전송
ALLOWED_FIDS: frozenset[str] = frozenset({'10', '11', '12', '14', '228'})

# 인코딩 캐시: (data_hash, fids_tuple) -> (text, binary)
_encoding_cache: OrderedDict[tuple[str, tuple[str, ...]], tuple[str, None]] = OrderedDict()
_ENCODING_CACHE_MAX_SIZE = 100

# real-data key shortening 매핑
_KEY_SHORTEN: dict[str, str] = {"type": "t", "item": "i", "values": "v"}

def _encode_realdata(data: dict, subscribed_fids: frozenset[str] | None = None) -> tuple[str, None]:
    """real-data 메시지를 FID 필터 + key shorten으로 인코딩.

    Args:
        data: 원본 real-data 메시지
        subscribed_fids: 클라이언트 구독 FID (None이면 ALLOWED_FIDS 사용)

    Returns:
        (text_frame, None) — 텍스트 프레임 전송
    """
    # FID 필터링: values에서 구독된 FID만 유지
    target_fids = subscribed_fids if subscribed_fids is not None else ALLOWED_FIDS
    values = data.get("values")
    filtered_values: Any = values
    if isinstance(values, dict):
        filtered_values = {k: v for k, v in values.items() if k in target_fids}

    # 캐시 키 생성: data 해시 + fids 튜플
    import hashlib
    data_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
    data_hash = hashlib.md5(data_str.encode('utf-8')).hexdigest()
    fids_tuple = tuple(sorted(target_fids))
    cache_key = (data_hash, fids_tuple)

    # 캐시 확인
    global _encoding_cache
    if cache_key in _encoding_cache:
        return _encoding_cache[cache_key]

    # key shortening: type→t, item→i, values→v
    shortened: dict[str, Any] = {}
    for key, val in data.items():
        if key == "values":
            shortened[_KEY_SHORTEN.get(key, key)] = filtered_values
        elif key in _KEY_SHORTEN:
            shortened[_KEY_SHORTEN[key]] = val
        else:
            shortened[key] = val

    # _v 스탬프 추가
    if "_v" not in shortened:
        shortened["_v"] = 1

    payload = json.dumps({"event": "real-data", "data": shortened}, ensure_ascii=False)

    # 캐시 저장 (LRU)
    _encoding_cache[cache_key] = (payload, None)
    if len(_encoding_cache) > _ENCODING_CACHE_MAX_SIZE:
        _encoding_cache.popitem(last=False)

    return payload, None


class WSManager:
    """WebSocket 연결 관리 — 즉시 broadcast."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        # per-client 활성 페이지 추적
        self._client_active_page: dict[WebSocket, str] = {}
        # per-client 구독 FID 추적 (미설정 시 ALLOWED_FIDS 사용)
        self._client_subscribed_fids: dict[WebSocket, frozenset[str]] = {}
        self._shutdown_timer: asyncio.TimerHandle | None = None

    # ------------------------------------------------------------------
    # 클라이언트 등록 / 해제
    # ------------------------------------------------------------------

    async def register(self, ws: WebSocket) -> None:
        """클라이언트를 _clients set에 추가."""
        self._clients.add(ws)
        if self._shutdown_timer is not None:
            self._shutdown_timer.cancel()
            self._shutdown_timer = None
            logger.info("[연결] 재연결 감지 — shutdown 타이머 취소")
        logger.debug("[연결] 클라이언트 연결 (총 %d)", len(self._clients))
        # 클라이언트 연결 시점 초기 데이터 전송 (타이밍 문제 해결)
        await self._send_initial_data_on_connect(ws)

    def unregister(self, ws: WebSocket) -> None:
        """클라이언트를 _clients set에서 제거."""
        self._clients.discard(ws)
        self._client_active_page.pop(ws, None)
        self._client_subscribed_fids.pop(ws, None)
        if not self._clients and self._shutdown_timer is None:
            try:
                loop = asyncio.get_running_loop()
                self._shutdown_timer = loop.call_later(1.0, self._send_sigterm)
                logger.info("[연결] 전체 WS 끊김 — 1초 후 shutdown 예약 (새로고침 대기)")
            except RuntimeError:
                logger.warning("[WS] shutdown 타이머 예약 실패 — 이벤트 루프 없음", exc_info=True)
        logger.debug("[연결] 클라이언트 해제 (총 %d)", len(self._clients))

    # ------------------------------------------------------------------
    # Per-client active page 관리
    # ------------------------------------------------------------------

    def set_active_page(self, ws: WebSocket, page: str) -> None:
        """클라이언트의 활성 페이지 설정."""
        self._client_active_page[ws] = page

    def clear_active_page(self, ws: WebSocket) -> None:
        """클라이언트의 활성 페이지 해제."""
        self._client_active_page.pop(ws, None)

    def get_active_pages(self) -> set[str]:
        """현재 활성화된 페이지 집합 반환."""
        return set(self._client_active_page.values())

    # ------------------------------------------------------------------
    # Per-client subscribed FID 관리
    # ------------------------------------------------------------------

    def set_subscribed_fids(self, ws: WebSocket, fids: list[str]) -> None:
        """클라이언트의 구독 FID 설정."""
        self._client_subscribed_fids[ws] = frozenset(fids)
        logger.debug("[구독] 클라이언트 FID 구독 설정: %s", fids)

    def clear_subscribed_fids(self, ws: WebSocket) -> None:
        """클라이언트의 구독 FID 해제 (기본 ALLOWED_FIDS 사용)."""
        self._client_subscribed_fids.pop(ws, None)
        logger.debug("[구독] 클라이언트 FID 구독 해제")

    # ------------------------------------------------------------------
    # 메시지 전송
    # ------------------------------------------------------------------

    @staticmethod
    def _stamp(data: dict) -> dict:
        """페이로드에 스키마 버전(_v) 필드를 자동 삽입한다."""
        if "_v" not in data:
            data["_v"] = 1
        return data

    async def _send_broadcast(self, event_type: str, data: dict) -> None:
        """모든 클라이언트에게 이벤트 즉시 전송."""
        message = json.dumps({"event": event_type, "data": self._stamp(data)}, ensure_ascii=False)
        dead: set[WebSocket] = set()
        for ws in set(self._clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
                logger.debug("[연결] WS broadcast 전송 실패 — 클라이언트 제거", exc_info=True)
        for ws in dead:
            self.unregister(ws)

    async def _send_realdata_immediate(self, text: str) -> None:
        """real-data 즉시 전송 — 수신 즉시 모든 클라이언트에 전달."""
        dead: set[WebSocket] = set()
        for ws in set(self._clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
                logger.debug("[연결] WS real-data 즉시 전송 실패 — 클라이언트 제거", exc_info=True)
        for ws in dead:
            self.unregister(ws)

    async def _send_realdata_encoded(self, data: dict, code: str) -> None:
        """real-data 전송 — 클라이언트별 FID 구독 반영.

        동일한 subscribed_fids를 가진 클라이언트 그룹별로 인코딩을 한 번만 수행하여
        CPU 부하를 방지한다. 페이지 필터링은 프론트엔드에서 처리한다 (SSOT 원칙).
        """
        # 클라이언트를 subscribed_fids별로 그룹화
        fids_to_clients: dict[frozenset[str], list[WebSocket]] = {}
        dead: set[WebSocket] = set()

        for ws in set(self._clients):
            # subscribed_fids 그룹화 — None이면 ALLOWED_FIDS(기본값) 그룹에 포함
            subscribed_fids = self._client_subscribed_fids.get(ws) or ALLOWED_FIDS
            if subscribed_fids not in fids_to_clients:
                fids_to_clients[subscribed_fids] = []
            fids_to_clients[subscribed_fids].append(ws)

        # 그룹별로 인코딩 후 전송
        for subscribed_fids, clients in fids_to_clients.items():
            text_frame, binary_frame = _encode_realdata(data, subscribed_fids)
            for ws in clients:
                try:
                    if binary_frame is not None:
                        await ws.send_bytes(binary_frame)
                    elif text_frame is not None:
                        await ws.send_text(text_frame)
                except Exception:
                    dead.add(ws)
                    logger.debug("[연결] WS real-data 인코딩 전송 실패 — 클라이언트 제거", exc_info=True)

        for ws in dead:
            self.unregister(ws)

    async def broadcast_to_pages(self, event_type: str, data: dict, pages: set[str]) -> None:
        """특정 페이지에 활성화된 클라이언트에게만 즉시 전송.

        pages: 전송 대상 페이지 집합 (예: {"profit-overview", "sell-position"})
        """
        if not self._clients or not pages:
            return

        # 페이지별 클라이언트 필터링
        target_clients = {ws for ws, page in self._client_active_page.items() if page in pages}
        if not target_clients:
            return

        await self._send_to_pages_immediate(event_type, data, target_clients)

    async def _send_to_pages_immediate(self, event_type: str, data: dict, target_clients: set[WebSocket]) -> None:
        """특정 클라이언트 집합에 즉시 전송."""
        message = json.dumps({"event": event_type, "data": self._stamp(data)}, ensure_ascii=False)
        dead: set[WebSocket] = set()
        for ws in target_clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
                logger.debug("[연결] WS 페이지별 전송 실패 — 클라이언트 제거", exc_info=True)
        for ws in dead:
            self.unregister(ws)

    async def broadcast(self, event_type: str, data: dict) -> None:
        """모든 클라이언트에 즉시 전송.

        real-data: FID 필터 + key shorten 후 클라이언트별 구독 FID 반영하여 즉시 전송
        기타 이벤트: _send_broadcast 즉시 전송
        """
        if not self._clients:
            return
        if event_type == "real-data":
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            raw_code = str(data.get("item") or "").strip()
            code = _base_stk_cd(raw_code) if raw_code else ""
            await self._send_realdata_encoded(data, code)
            return
        await self._send_broadcast(event_type, data)

    def broadcast_threadsafe(self, event_type: str, data: dict, loop: asyncio.AbstractEventLoop) -> None:
        """스레드풀(asyncio.to_thread) 내부에서 안전하게 호출 가능한 브로드캐스트.

        run_coroutine_threadsafe()로 메인 이벤트 루프에 coroutine을 예약하므로
        이벤트 루프가 없는 스레드에서도 RuntimeError 없이 동작한다.
        """
        if not self._clients:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(event_type, data), loop)

    async def _send(self, ws: WebSocket, text: str) -> None:
        """단일 클라이언트 전송. 실패 시 해당 클라이언트만 제거."""
        try:
            await ws.send_text(text)
        except Exception:
            self.unregister(ws)
            logger.debug("[연결] WS 단일 전송 실패 — 클라이언트 제거", exc_info=True)

    async def send_to(self, ws: WebSocket, event_type: str, data: dict) -> None:
        """특정 클라이언트에만 유니캐스트 (initial-snapshot용)."""
        stamped = self._stamp(data)
        text = json.dumps({"event": event_type, "data": stamped}, ensure_ascii=False)
        try:
            await ws.send_text(text)
            logger.debug("[연결] %s 화면전송 완료 (size=%d bytes)", event_type, len(text))
        except Exception as e:
            logger.warning("[연결] %s 화면전송 실패: %s", event_type, str(e), exc_info=True)
            self.unregister(ws)

    def _send_sigterm(self) -> None:
        """WS 클라이언트 전체 끊김 후 1초 내 재연결 없으면 백엔드 종료.
        단, 브로커 재연결 루프 진행 중에는 종료하지 않고 타이머만 리셋."""
        import os
        import signal
        from backend.app.services.engine_state import state
        if self._clients:
            self._shutdown_timer = None
            return
        if state.shutdown_requested:
            return
        if state.connector_manager is not None and not state.connector_manager.is_connected():
            self._shutdown_timer = None
            logger.info("[연결] 브로커 재연결 중 — shutdown 보류")
            return
        state.shutdown_requested = True
        logger.info("[연결] 재연결 없음 — SIGTERM 전송 (Graceful Shutdown)")
        os.kill(os.getpid(), signal.SIGTERM)

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    async def close_all(self) -> None:
        """모든 클라이언트 ws.close() + _clients 비우기."""
        for ws in set(self._clients):
            try:
                await ws.close()
            except Exception:
                logger.debug("[연결] WS 클라이언트 종료 실패", exc_info=True)
        self._clients.clear()
        if self._shutdown_timer is not None:
            self._shutdown_timer.cancel()
            self._shutdown_timer = None

    # ------------------------------------------------------------------
    # 초기 데이터 전송 (타이밍 문제 해결)
    # ------------------------------------------------------------------

    async def _send_initial_data_on_connect(self, ws: WebSocket) -> None:
        """클라이언트 연결 시점 초기 데이터 전송."""
        try:
            # buy-targets 초기 데이터 전송
            from backend.app.services.sector_data_provider import get_buy_targets_sector_stocks
            targets = await get_buy_targets_sector_stocks()
            if targets:
                data = {"buy_targets": targets, "_v": 1}
                message = json.dumps({"event": "buy-targets-update", "data": data}, ensure_ascii=False)
                await ws.send_text(message)
                logger.debug("[연결] buy-targets 초기 데이터 전송 완료 (size=%d bytes)", len(message))
        except Exception as e:
            logger.warning("[연결] 초기 데이터 전송 실패: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # 프로퍼티
    # ------------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """현재 연결된 WebSocket 클라이언트 수."""
        return len(self._clients)


# 전역 싱글턴
ws_manager = WSManager()
