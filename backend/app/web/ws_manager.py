# -*- coding: utf-8 -*-
"""WebSocket 클라이언트 연결 관리 — 즉시 broadcast.

set[WebSocket] 기반 직접 참조.
broadcast()는 async 함수로, 모든 이벤트를 await 기반 직접 전송한다.
"""
from __future__ import annotations
import logging
from typing import Any
from collections import OrderedDict
from fastapi import WebSocket
from backend.app.db.json_utils import dumps
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
    data_str = dumps(data, sort_keys=True)
    data_hash = hashlib.md5(data_str.encode('utf-8')).hexdigest()
    fids_tuple = tuple(sorted(target_fids))
    cache_key = (data_hash, fids_tuple)

    # 캐시 확인
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

    payload = dumps({"event": "real-data", "data": shortened})

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
        # ── 종목별 구독 페이지 추적 (마스터 캐시 단일 시세 소스 — 설계 결정 2) ──
        # _symbol_subscribers: {종목코드: set[WebSocket]} — 해당 종목을 구독 중인 클라이언트 집합.
        # _client_subscribed_codes: {WebSocket: set[str]} — 클라이언트가 구독 중인 종목 코드 (해제·정리용).
        # 0→1 전환 시 해당 종목 실시간 전송 시작, 1→0 시 중단 (설계 결정 2, P10 SSOT).
        self._symbol_subscribers: dict[str, set[WebSocket]] = {}
        self._client_subscribed_codes: dict[WebSocket, set[str]] = {}

    # ------------------------------------------------------------------
    # 클라이언트 등록 / 해제
    # ------------------------------------------------------------------

    async def register(self, ws: WebSocket) -> None:
        """클라이언트를 _clients set에 추가."""
        self._clients.add(ws)
        logger.debug("[연결] 클라이언트 연결 (총 %d)", len(self._clients))
        # 클라이언트 연결 시점 초기 데이터 전송 (타이밍 문제 해결)
        await self._send_initial_data_on_connect(ws)

    def unregister(self, ws: WebSocket) -> None:
        """클라이언트를 _clients set에서 제거 + 구독 코드 정리."""
        self._clients.discard(ws)
        self._client_active_page.pop(ws, None)
        self._client_subscribed_fids.pop(ws, None)
        # 종목 구독 정리 (마스터 캐시 구독 — 설계 결정 2)
        self._cleanup_subscribed_codes(ws)
        logger.debug("[연결] 클라이언트 해제 (총 %d)", len(self._clients))

    # ------------------------------------------------------------------
    # Per-client active page 관리
    # ------------------------------------------------------------------

    def set_active_page(self, ws: WebSocket, page: str) -> None:
        """클라이언트의 활성 페이지 설정."""
        self._client_active_page[ws] = page

    def clear_active_page(self, ws: WebSocket) -> None:
        """클라이언트의 활성 페이지 해제 + 종목 구독 해제."""
        self._client_active_page.pop(ws, None)
        # 페이지 비활성화 시 해당 클라이언트의 종목 구독도 해제 (설계 결정 2)
        self._cleanup_subscribed_codes(ws)

    def get_active_pages(self) -> set[str]:
        """현재 활성화된 페이지 집합 반환."""
        return set(self._client_active_page.values())

    def get_clients_for_page(self, page: str) -> set[WebSocket]:
        """특정 페이지에 활성화된 클라이언트 집합 반환 (활성 연결 갱신용)."""
        return {ws for ws, p in self._client_active_page.items() if p == page}

    # ------------------------------------------------------------------
    # 종목별 구독 관리 (마스터 캐시 단일 시세 소스 — 설계 결정 2)
    # ------------------------------------------------------------------

    def subscribe_codes(self, ws: WebSocket, page: str, codes: list[str]) -> set[str]:
        """클라이언트가 페이지에서 구독할 종목 코드 등록.

        기존 구독 코드를 해제하고 새 코드 집합으로 교체 (페이지 전환 시 자연스러운 동작).
        0→1 전환 종목(새로 구독 시작) 집합을 반환 — 호출부에서 snapshot 전송용.

        Returns:
            newly_subscribed: 이 클라이언트가 새로 구독하기 시작한 종목 코드 집합
            (다른 클라이언트가 이미 구독 중이어도 이 클라이언트 기준으로 신규).
        """
        # 기존 구독 코드 해제
        self._cleanup_subscribed_codes(ws)

        new_codes = {c for c in codes if c}
        self._client_subscribed_codes[ws] = new_codes.copy()

        newly_subscribed: set[str] = set()
        for code in new_codes:
            subscribers = self._symbol_subscribers.get(code)
            if subscribers is None:
                subscribers = set()
                self._symbol_subscribers[code] = subscribers
            if not subscribers:
                # 0→1 전환 — 이 종목의 실시간 전송 시작
                newly_subscribed.add(code)
            subscribers.add(ws)

        logger.debug(
            "[구독] 페이지=%s 종목 %d건 구독 (신규 전송 시작 %d건)",
            page, len(new_codes), len(newly_subscribed),
        )
        return newly_subscribed

    def update_subscription_diff(
        self, ws: WebSocket, page: str, new_codes: list[str],
    ) -> tuple[set[str], set[str]]:
        """같은 페이지에서 대상 변경 시 diff 기반 갱신 (페이지 전환 아님).

        유지 종목은 그대로 두고, 추가 종목만 등록·스냅샷 전송, 제거 종목만 해지.
        유지 종목에 불필요한 전체 스냅샷을 반복하지 않는다 (태스크 2세션 §6).

        Returns:
            (newly_subscribed, removed_codes):
              newly_subscribed — 이 클라이언트가 새로 구독하기 시작한 종목 (스냅샷 전송용)
              removed_codes — 이 클라이언트에서 해지된 종목 (더 이상 실시간 전송 안 함)
        """
        prev_codes = self._client_subscribed_codes.get(ws, set())
        new_set = {c for c in new_codes if c}
        added = new_set - prev_codes
        removed = prev_codes - new_set

        # 제거 종목 해지
        for code in removed:
            subscribers = self._symbol_subscribers.get(code)
            if subscribers is not None:
                subscribers.discard(ws)
                if not subscribers:
                    del self._symbol_subscribers[code]

        # 추가 종목 등록
        newly_subscribed: set[str] = set()
        for code in added:
            subscribers = self._symbol_subscribers.get(code)
            if subscribers is None:
                subscribers = set()
                self._symbol_subscribers[code] = subscribers
            if not subscribers:
                newly_subscribed.add(code)
            subscribers.add(ws)

        # 클라이언트 구독 코드 갱신
        self._client_subscribed_codes[ws] = new_set.copy()

        logger.debug(
            "[구독] 페이지=%s 대상 변경 (추가 %d, 제거 %d, 유지 %d)",
            page, len(added), len(removed), len(prev_codes & new_set),
        )
        return newly_subscribed, removed

    def _cleanup_subscribed_codes(self, ws: WebSocket) -> None:
        """클라이언트의 종목 구독 전부 해제 (페이지 전환·연결 해제 시)."""
        codes = self._client_subscribed_codes.pop(ws, None)
        if not codes:
            return
        for code in codes:
            subscribers = self._symbol_subscribers.get(code)
            if subscribers is not None:
                subscribers.discard(ws)
                if not subscribers:
                    # 1→0 전환 — 이 종목의 실시간 전송 중단
                    del self._symbol_subscribers[code]

    def get_subscribers_for_code(self, code: str) -> set[WebSocket]:
        """특정 종목을 구독 중인 클라이언트 집합 반환 (틱/호가/PGM 이벤트 라우팅용)."""
        return self._symbol_subscribers.get(code, set())

    # ------------------------------------------------------------------
    # Per-client subscribed FID 관리
    # ------------------------------------------------------------------

    def set_subscribed_fids(self, ws: WebSocket, fids: list[str]) -> None:
        """클라이언트의 구독 FID 설정."""
        self._client_subscribed_fids[ws] = frozenset(fids)

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
        message = dumps({"event": event_type, "data": self._stamp(data)})
        dead: set[WebSocket] = set()
        for ws in set(self._clients):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
                logger.debug("[연결] 실시간 통신 전송 실패 — 클라이언트 제거", exc_info=True)
        for ws in dead:
            self.unregister(ws)

    async def _send_realdata_encoded(self, data: dict, code: str, subscribers: set[WebSocket] | None = None) -> None:
        """real-data 전송 — 클라이언트별 FID 구독 반영.

        동일한 subscribed_fids를 가진 클라이언트 그룹별로 인코딩을 한 번만 수행하여
        CPU 부하를 방지한다. subscribers가 지정되면 해당 클라이언트 집합에게만 전송 (마스터 캐시 구독 모델).
        """
        # 전송 대상 클라이언트: subscribers가 지정되면 해당 집합, 아니면 전체
        target_clients = subscribers if subscribers is not None else set(self._clients)
        if not target_clients:
            return

        # 클라이언트를 subscribed_fids별로 그룹화
        fids_to_clients: dict[frozenset[str], list[WebSocket]] = {}
        dead: set[WebSocket] = set()

        for ws in target_clients:
            if ws not in self._clients:
                continue
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
                    logger.debug("[연결] 실시간 통신 실시간 데이터 인코딩 전송 실패 — 클라이언트 제거", exc_info=True)

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
        message = dumps({"event": event_type, "data": self._stamp(data)})
        dead: set[WebSocket] = set()
        for ws in target_clients:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
                logger.debug("[연결] 실시간 통신 페이지별 전송 실패 — 클라이언트 제거", exc_info=True)
        for ws in dead:
            self.unregister(ws)

    async def broadcast(self, event_type: str, data: dict) -> None:
        """모든 클라이언트에 즉시 전송.

        real-data: 종목 구독자에게만 FID 필터 + key shorten 후 전송 (마스터 캐시 구독 모델)
        기타 이벤트: _send_broadcast 즉시 전송
        """
        if not self._clients:
            return
        if event_type == "real-data":
            from backend.app.services.engine_symbol_utils import _base_stk_cd
            raw_code = str(data.get("item") or "").strip()
            code = _base_stk_cd(raw_code) if raw_code else ""
            # 구독자가 없으면 전송 생략 (페이지별 구독 push 모델 — 설계 결정 2)
            subscribers = self.get_subscribers_for_code(code) if code else set()
            if not subscribers:
                return
            await self._send_realdata_encoded(data, code, subscribers)
            return
        await self._send_broadcast(event_type, data)

    async def send_to(self, ws: WebSocket, event_type: str, data: dict) -> None:
        """특정 클라이언트에만 유니캐스트 (initial-snapshot용)."""
        stamped = self._stamp(data)
        text = dumps({"event": event_type, "data": stamped})
        try:
            await ws.send_text(text)
        except Exception as e:
            logger.warning("[연결] %s 화면 전송 실패: %s", event_type, str(e), exc_info=True)
            self.unregister(ws)

    async def broadcast_to_code_subscribers(self, event_type: str, data: dict, code: str) -> None:
        """특정 종목을 구독 중인 클라이언트에게만 전송 (master-cache-delta 라우팅용).

        마스터 캐시 단일 시세 소스 — 틱/호가/PGM/뉴스 이벤트 시 해당 종목 구독 페이지에만 push.
        """
        subscribers = self.get_subscribers_for_code(code)
        if not subscribers:
            return
        message = dumps({"event": event_type, "data": self._stamp(data)})
        dead: set[WebSocket] = set()
        for ws in subscribers:
            if ws not in self._clients:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
                logger.debug("[연결] 종목 구독자 전송 실패 — 클라이언트 제거", exc_info=True)
        for ws in dead:
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
                logger.debug("[연결] 실시간 통신 클라이언트 종료 실패", exc_info=True)
        self._clients.clear()

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
                message = dumps({"event": "buy-targets-update", "data": data})
                await ws.send_text(message)
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
