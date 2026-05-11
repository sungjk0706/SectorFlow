# -*- coding: utf-8 -*-
"""WebSocket 클라이언트 연결 관리 — throttled broadcast.

set[WebSocket] 기반 직접 참조.
broadcast()는 동기 함수로, 메시지를 큐에 적재하고 0.1초마다 배치 전송한다.

메시지 분류:
  - 상태형(STATE_EVENTS): 0.1초 내 최신값만 유지 (coalescing)
  - 이벤트형: 전부 누적 후 순서 보장 전송
"""
from __future__ import annotations

import asyncio
import json
import logging
import zlib
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL = 0.1  # 배치 전송 주기 (초)

# 상태형 이벤트: 0.1초 내 마지막 값만 유지 (coalescing)
_STATE_EVENTS: frozenset[str] = frozenset({
    "trade-price",
    "orderbook-update",
    "index-refresh",
    "account-update",
    "engine-status",
    "sector-scores",
    "buy-targets-delta",
    "buy-limit-status",
    "ws-subscribe-status",
    "snapshot-update",
    "sector-stocks-delta",
})

# real-data FID 필터: 프론트엔드에서 사용하는 FID만 전송
ALLOWED_FIDS: frozenset[str] = frozenset({'10', '11', '12', '14', '228'})

# real-data key shortening 매핑
_KEY_SHORTEN: dict[str, str] = {"type": "t", "item": "i", "values": "v"}

# zlib 압축 임계값 (바이트)
_COMPRESS_THRESHOLD = 512


def _encode_realdata(data: dict) -> tuple[str | None, bytes | None]:
    """real-data 메시지를 FID 필터 + key shorten + 선택적 zlib 압축으로 인코딩.

    Returns:
        (text_frame, None) — 512바이트 이하: 텍스트 프레임 전송
        (None, binary_frame) — 512바이트 초과: zlib 압축 바이너리 프레임 전송
        zlib 압축 실패 시 graceful degradation → 텍스트 프레임 전송
    """
    # FID 필터링: values에서 허용된 FID만 유지
    values = data.get("values")
    if isinstance(values, dict):
        filtered_values = {k: v for k, v in values.items() if k in ALLOWED_FIDS}
    else:
        filtered_values = values

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
    payload_bytes = payload.encode("utf-8")

    if len(payload_bytes) > _COMPRESS_THRESHOLD:
        # zlib 압축 시도
        try:
            compressed = zlib.compress(payload_bytes)
            return None, compressed
        except Exception:
            # graceful degradation: 압축 실패 시 텍스트 전송
            return payload, None

    return payload, None


class WSManager:
    """WebSocket throttled 연결 관리."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        # per-client 활성 페이지 추적
        self._client_active_page: dict[WebSocket, str] = {}
        # 상태형: {event_type: data} — 최신값만 유지
        self._state_queue: dict[str, dict[str, Any]] = {}
        # 이벤트형: [(event_type, data), ...] — 순서 보장
        self._event_queue: list[tuple[str, dict[str, Any]]] = []
        self._flush_task: asyncio.Task | None = None

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
        self._client_active_page.pop(ws, None)
        logger.debug("[실시간] 클라이언트 해제 (총 %d)", len(self._clients))

    # ------------------------------------------------------------------
    # Per-client active page 관리
    # ------------------------------------------------------------------

    def set_active_page(self, ws: WebSocket, page: str) -> None:
        """클라이언트의 활성 페이지 설정."""
        self._client_active_page[ws] = page

    def clear_active_page(self, ws: WebSocket) -> None:
        """클라이언트의 활성 페이지 해제."""
        self._client_active_page.pop(ws, None)

    # ------------------------------------------------------------------
    # 내부 큐 관리
    # ------------------------------------------------------------------

    def _ensure_flush_task(self) -> None:
        """flush 루프 태스크가 없으면 생성."""
        if self._flush_task is None or self._flush_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._flush_task = loop.create_task(self._flush_loop())
            except RuntimeError:
                pass

    async def _flush_loop(self) -> None:
        """_FLUSH_INTERVAL마다 큐를 비우고 전송."""
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL)
            if not self._clients:
                self._state_queue.clear()
                self._event_queue.clear()
                continue
            await self._flush()

    async def _flush(self) -> None:
        """큐에 쌓인 메시지를 모두 전송."""
        # 이벤트형 먼저 (순서 중요)
        events = self._event_queue
        self._event_queue = []
        # 상태형
        states = self._state_queue
        self._state_queue = {}

        batch: list[str] = []
        for event_type, data in events:
            batch.append(json.dumps({"event": event_type, "data": self._stamp(data)}, ensure_ascii=False))
        for event_type, data in states.items():
            batch.append(json.dumps({"event": event_type, "data": self._stamp(data)}, ensure_ascii=False))

        if not batch:
            return

        dead: set[WebSocket] = set()
        for ws in set(self._clients):
            for text in batch:
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.add(ws)
                    break
        for ws in dead:
            self.unregister(ws)

    # ------------------------------------------------------------------
    # 메시지 전송
    # ------------------------------------------------------------------

    @staticmethod
    def _stamp(data: dict) -> dict:
        """페이로드에 스키마 버전(_v) 필드를 자동 삽입한다."""
        if "_v" not in data:
            data["_v"] = 1
        return data

    async def _send_realdata_immediate(self, text: str) -> None:
        """real-data 즉시 전송 — flush 큐 우회, 수신 즉시 모든 클라이언트에 전달.

        text 또는 binary(zlib 압축) 프레임으로 전송.
        """
        dead: set[WebSocket] = set()
        for ws in set(self._clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.unregister(ws)

    def _is_code_relevant_for_page(self, page: str, code: str) -> bool:
        """페이지별 종목 코드 관련성 판별. 단일 스레드 — 락 불필요."""
        if page == "sector-analysis":
            # 업종별종목시세 테이블용: layout 종목 + pending 종목
            from app.services.engine_account_notify import _layout_code_set
            import app.services.engine_service as _es
            return code in _layout_code_set or code in _es._pending_stock_details
        elif page == "buy-target":
            # 매수후보 종목만
            import app.services.engine_service as _es
            ss = _es._sector_summary_cache
            if not ss:
                return True  # 캐시 미초기화 → 안전 폴백
            return any(bt.stock.code == code for bt in ss.buy_targets) or any(bt.stock.code == code for bt in ss.blocked_targets)
        elif page == "sell-position":
            # 보유종목만
            from app.services.engine_account_notify import _positions_code_set
            return code in _positions_code_set
        elif page in ("profit-overview", "settings", "buy-settings", "sell-settings", "general-settings", "sector-custom"):
            return False  # real-data 전송 안 함
        # 알 수 없는 페이지 → 전체 전송 (안전 폴백)
        return True

    async def _send_realdata_encoded(self, text: str | None, binary: bytes | None, code: str) -> None:
        """per-client 필터링 적용 real-data 전송 — text 또는 binary 프레임."""
        dead: set[WebSocket] = set()
        for ws in set(self._clients):
            # per-client active_page 필터링
            page = self._client_active_page.get(ws)
            if page and not self._is_code_relevant_for_page(page, code):
                continue  # 이 클라이언트에는 전송 생략
            try:
                if binary is not None:
                    await ws.send_bytes(binary)
                elif text is not None:
                    await ws.send_text(text)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.unregister(ws)

    def broadcast(self, event_type: str, data: dict) -> None:
        """모든 클라이언트에 throttled 전송 (동기, await 없음).

        real-data: FID 필터 + key shorten + zlib 압축 후 즉시 전송
        상태형: _state_queue에 최신값 덮어쓰기 (coalescing)
        이벤트형: _event_queue에 순서대로 누적
        0.1초마다 _flush_loop가 일괄 전송.
        """
        if not self._clients:
            return
        if event_type == "real-data":
            try:
                loop = asyncio.get_running_loop()
                # 종목 코드 추출 + 정규화 (per-client 필터링용)
                from app.services.engine_symbol_utils import _format_kiwoom_reg_stk_cd
                raw_code = str(data.get("item") or "").strip()
                code = _format_kiwoom_reg_stk_cd(raw_code) if raw_code else ""
                text_frame, binary_frame = _encode_realdata(data)
                loop.create_task(self._send_realdata_encoded(text_frame, binary_frame, code))
            except RuntimeError:
                pass
            return
        self._ensure_flush_task()
        if event_type in _STATE_EVENTS:
            self._state_queue[event_type] = data
        else:
            self._event_queue.append((event_type, data))

    def broadcast_threadsafe(self, event_type: str, data: dict, loop: asyncio.AbstractEventLoop) -> None:
        """스레드풀(asyncio.to_thread) 내부에서 안전하게 호출 가능한 브로드캐스트.

        call_soon_threadsafe()로 메인 이벤트 루프에 coroutine을 예약하므로
        이벤트 루프가 없는 스레드에서도 RuntimeError 없이 동작한다.
        """
        if not self._clients:
            return
        loop.call_soon_threadsafe(self.broadcast, event_type, dict(data))

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
