# -*- coding: utf-8 -*-
"""WebSocket 클라이언트 연결 관리 — fire-and-forget broadcast.

set[WebSocket] 기반 직접 참조. 버퍼/큐/Lock 없음.
broadcast()는 동기 함수로, create_task(_send())만 호출하고 즉시 반환한다."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """WebSocket fire-and-forget 연결 관리."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    # ------------------------------------------------------------------
    # 클라이언트 등록 / 해제
    # ------------------------------------------------------------------

    def register(self, ws: WebSocket) -> None:
        """클라이언트를 _clients set에 추가."""
        self._clients.add(ws)
        logger.debug("[실시간] 클라이언트 연결 (총 %d)", len(self._clients))

    def unregister(self, ws: WebSocket) -> None:
        """클라이언트를 _clients set에서 제거."""
        self._clients.discard(ws)
        logger.debug("[실시간] 클라이언트 해제 (총 %d)", len(self._clients))

    # ------------------------------------------------------------------
    # 메시지 전송
    # ------------------------------------------------------------------

    @staticmethod
    def _stamp(data: dict) -> dict:
        """페이로드에 스키마 버전(_v) 필드를 자동 삽입한다."""
        if "_v" not in data:
            data["_v"] = 1
        return data

    def broadcast(self, event_type: str, data: dict) -> None:
        """모든 클라이언트에 fire-and-forget 전송 (동기, await 없음).

        _stamp(data) → JSON 직렬화 → _clients 순회 →
        create_task(_send(ws, text)) → 즉시 반환.
        """
        if not self._clients:
            return
        stamped = self._stamp(data)
        text = json.dumps({"event": event_type, "data": stamped}, ensure_ascii=False)
        for ws in set(self._clients):
            asyncio.create_task(self._send(ws, text))

    def broadcast_threadsafe(self, event_type: str, data: dict, loop: asyncio.AbstractEventLoop) -> None:
        """스레드풀(asyncio.to_thread) 내부에서 안전하게 호출 가능한 브로드캐스트.

        call_soon_threadsafe()로 메인 이벤트 루프에 coroutine을 예약하므로
        이벤트 루프가 없는 스레드에서도 RuntimeError 없이 동작한다.
        """
        if not self._clients:
            return
        stamped = self._stamp(dict(data))
        text = json.dumps({"event": event_type, "data": stamped}, ensure_ascii=False)

        async def _do_broadcast() -> None:
            for ws in set(self._clients):
                asyncio.create_task(self._send(ws, text))

        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_do_broadcast(), loop=loop))

    async def _send(self, ws: WebSocket, text: str) -> None:
        """단일 클라이언트 전송. 실패 시 해당 클라이언트만 제거."""
        try:
            await ws.send_text(text)
        except Exception:
            self.unregister(ws)

    async def send_to(self, ws: WebSocket, event_type: str, data: dict) -> None:
        """특정 클라이언트에만 유니캐스트 (initial-snapshot용)."""
        stamped = self._stamp(data)
        text = json.dumps({"event": event_type, "data": stamped}, ensure_ascii=False)
        try:
            await ws.send_text(text)
            logger.debug("[실시간연결] %s 화면전송 완료 (size=%d bytes)", event_type, len(text))
        except Exception as e:
            logger.warning("[실시간연결] %s 화면전송 실패: %s", event_type, str(e))
            self.unregister(ws)

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    async def close_all(self) -> None:
        """모든 클라이언트 ws.close() + _clients 비우기."""
        for ws in set(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()

    # ------------------------------------------------------------------
    # 프로퍼티
    # ------------------------------------------------------------------

    @property
    def client_count(self) -> int:
        """현재 연결된 WebSocket 클라이언트 수."""
        return len(self._clients)


# 전역 싱글턴
ws_manager = WSManager()
