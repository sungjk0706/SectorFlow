# -*- coding: utf-8 -*-
"""
Broker Connector — 추상 브로커 커넥터 인터페이스

하이브리드 증권사 지원을 위한 추상 클래스.
구현 방식:
  - 폴링 방식: receive() 메서드 구현
  - 콜백 방식: set_message_callback() 지원

WS 콜백 인프라(_on_ws_message, set_message_callback, set_reconnect_success_callback,
_on_socket_disconnect, _make_queue_callback, _reconnect_loop)는 공통 구현을 제공 —
서브클래스는 __init__에서 _receive_callback/_on_reconnect_success/_ws_queue/
_reconnecting/_stop_reconnect/_connected/_token/_lock/_ws_uri 를 초기화하고
_get_token_async()·_reconnect_socket()을 구현하며, 필요 시 _on_reconnect_resubscribe()를 오버라이드.
"""
from __future__ import annotations
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from collections.abc import Callable

logger = logging.getLogger(__name__)

# 재연결 백오프 간격(초) — 양 증권사 공통(단순화). 최대 10회.
_RECONNECT_DELAYS: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 32, 32, 32, 32)


class DataPriority(Enum):
    """데이터 우선순위"""
    CRITICAL = auto()   # 체결, 잔고
    HIGH = auto()       # 호가
    NORMAL = auto()     # 차트, 지수


@dataclass
class DataMessage:
    """WS 수신 데이터 표준 포맷"""
    broker_id: str
    msg_type: str
    code: str | None
    payload: dict
    timestamp: float = field(default_factory=lambda: __import__('time').time())
    priority: DataPriority = DataPriority.NORMAL
    sequence: int | None = None



class BrokerConnector(ABC):
    """추상 브로커 커넥터"""

    # WS 콜백 인프라 — 서브클래스 __init__에서 초기화
    _receive_callback: Callable | None = None
    _on_reconnect_success: Callable | None = None
    _ws_queue: asyncio.Queue | None = None
    _reconnecting: bool = False
    _stop_reconnect: bool = False
    _connected: bool = False

    @property
    @abstractmethod
    def broker_id(self) -> str:
        """증권사 식별자 (예: 'kiwoom', 'ls')"""
        ...

    @property
    def _broker_display(self) -> str:
        """증권사 표시명 (로그용) — broker_id 기반."""
        from backend.app.core.broker_urls import BROKER_DISPLAY_NAMES
        return BROKER_DISPLAY_NAMES[self.broker_id]

    @abstractmethod
    async def connect(self) -> None:
        """WS 연결 수립"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """WS 연결 종료"""
        ...

    @abstractmethod
    async def subscribe(self, code: str, data_types: list[str]) -> bool:
        """종목 구독 등록 (예: ['0B', '0D'])"""
        ...

    async def receive(self) -> DataMessage | None:
        """데이터 수신 (블로킹) — 폴링 방식 커넥터용"""
        raise NotImplementedError("폴링 방식 커넥터는 receive()를 구현해야 합니다")

    def set_message_callback(self, callback: Callable[[dict], None]) -> None:
        """메시지 수신 콜백 설정 — 콜백 방식 커넥터용

        UnifiedWSManager가 자동으로 호출합니다.
        """
        self._receive_callback = callback

    def set_reconnect_success_callback(self, callback: Callable) -> None:
        """재연결 성공 시 호출될 콜백 설정 (ConnectorManager가 구독 복원에 사용)."""
        self._on_reconnect_success = callback

    async def _on_ws_message(self, payload: dict) -> None:
        """내부 소켓 콜백 → 핸들러 직접 호출 (코루틴/동기 콜백 분기)."""
        if self._receive_callback:
            if asyncio.iscoroutinefunction(self._receive_callback):
                await self._receive_callback(payload)
            else:
                self._receive_callback(payload)

    async def _on_socket_disconnect(self) -> None:
        """내부 소켓 연결 끊김 시 호출 — 재연결 루프 기동."""
        if self._stop_reconnect:
            return
        self._connected = False
        try:
            from backend.app.services.engine_state import state
            state.login_ok = False
        except Exception:
            logger.warning("[연결] %s 로그인 상태 초기화 실패", self._broker_display, exc_info=True)
        try:
            from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
            broadcast_ws_connection_status(False)
        except Exception:
            logger.warning("[연결] %s 연결 끊김 상태 알림 실패", self._broker_display, exc_info=True)
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            await self._reconnect_loop()
        finally:
            self._reconnecting = False

    async def _reconnect_loop(self) -> None:
        """통합 재연결 루프 — 지수 백오프(_RECONNECT_DELAYS)로 재시도.

        공통 흐름: 토큰 발급 → 소켓 재연결(서브클래스) → 로그인 상태 복원 →
        큐 클리어 → 연결 상태 전송 → 재구독 훅(서브클래스) → 구독 복원 콜백.
        """
        max_attempts = len(_RECONNECT_DELAYS)
        for attempt, delay in enumerate(_RECONNECT_DELAYS, start=1):
            if self._stop_reconnect:
                logger.info("[연결] %s 재연결 중단 (중지 신호)", self._broker_display)
                return
            logger.info("[연결] %s 재연결 시도 %d/%d — %d초 후", self._broker_display, attempt, max_attempts, delay)
            await asyncio.sleep(delay)
            if self._stop_reconnect:
                return
            try:
                token = await self._get_token_async()
                if not token:
                    logger.debug("[연결] %s 재연결 %d회: 토큰 발급 실패", self._broker_display, attempt)
                    continue
                await self._reconnect_socket(token)
                self._connected = True
                # 로그인 상태 복원 (양 증권사 공통)
                try:
                    from backend.app.services.engine_state import state
                    state.login_ok = True
                except Exception:
                    logger.debug("[연결] %s 로그인 상태 복원 실패", self._broker_display, exc_info=True)
                logger.info("[연결] %s 재연결 성공 (시도 %d회)", self._broker_display, attempt)
                # 재연결 성공 후 큐 클리어 (과거 데이터 제거)
                if self._ws_queue is not None:
                    cleared = 0
                    while not self._ws_queue.empty():
                        try:
                            self._ws_queue.get_nowait()
                            cleared += 1
                        except asyncio.QueueEmpty:
                            break
                    if cleared > 0:
                        logger.debug("[연결] %s 재연결 후 큐 정리 — %d건 폐기", self._broker_display, cleared)
                # 연결 상태 전송
                try:
                    from backend.app.services.ws_subscribe_control import broadcast_ws_connection_status
                    broadcast_ws_connection_status(True)
                except Exception:
                    logger.debug("[연결] %s 재연결 상태 전송 실패", self._broker_display, exc_info=True)
                # 서브클래스별 재구독 훅 (LS: JIF/NWS)
                try:
                    await self._on_reconnect_resubscribe()
                except Exception:
                    logger.debug("[연결] %s 재연결 후 재구독 훅 실패", self._broker_display, exc_info=True)
                # 구독 복원 콜백 (ConnectorManager가 REG 재전송)
                if self._on_reconnect_success:
                    await self._on_reconnect_success(self.broker_id)
                return
            except Exception as e:
                logger.warning("[연결] %s 재연결 %d회 실패: %s", self._broker_display, attempt, e, exc_info=True)
        logger.error("[연결] %s 최대 재연결 횟수(%d회) 초과 — 중단", self._broker_display, max_attempts, exc_info=True)

    @abstractmethod
    async def _get_token_async(self) -> str | None:
        """토큰 확보 (비동기) — 서브클래스에서 구현 (기존 REST API 인스턴스 재사용)."""
        ...

    @abstractmethod
    async def _reconnect_socket(self, token: str) -> None:
        """재연결 시 소켓만 다시 맺는다 (토큰은 이미 발급됨).

        서브클래스에서 self._token 설정 + 소켓 생성 + connect() 수행.
        실패 시 예외 발생 (호출자가 catch).
        """
        ...

    async def _on_reconnect_resubscribe(self) -> None:
        """재연결 성공 후 서브클래스별 재구독 훅 (기본 no-op).

        LS 커넥터는 JIF/NWS 재구독을 위해 오버라이드.
        """
        pass

    def _make_queue_callback(self) -> Callable[[dict], None] | None:
        """시세 큐 누락 정책 콜백 생성 — 큐 가득 시 가장 오래된 데이터 버리고 최신 유지.

        Producer-Consumer Queue가 설정되지 않은 경우 None 반환.
        """
        if self._ws_queue is None:
            return None
        _q = self._ws_queue
        _display = self._broker_display
        def _queue_put_with_drop(msg: dict) -> None:
            try:
                _q.put_nowait(msg)
            except asyncio.QueueFull:
                try:
                    _q.get_nowait()
                    _q.put_nowait(msg)
                    logger.debug("[연결] %s 데이터 큐 누락 발생 — 최신 데이터 유지", _display)
                except asyncio.QueueEmpty:
                    _q.put_nowait(msg)
        return _queue_put_with_drop

    @abstractmethod
    def is_connected(self) -> bool:
        """연결 상태 확인"""
        ...

    @abstractmethod
    def supports_ack(self) -> bool:
        """구독/해지 ACK 응답 지원 여부 반환"""
        ...

    async def subscribe_dynamic(self, codes: list[str]) -> bool:
        """동적 데이터 구독 등록 (기본 구현: 미지원)"""
        return False

    async def unsubscribe_dynamic(self, codes: list[str]) -> None:
        """동적 데이터 구독 해지 (기본 구현: 패스)"""
        pass

    async def subscribe_index(self) -> bool:
        """업종지수 실시간 구독 등록 (기본 구현: 미지원)"""
        return False

    async def subscribe_stocks(self, codes: list[str]) -> bool:
        """종목 리스트 실시간 구독 등록 (기본 구현: 미지원)"""
        return False

    async def unsubscribe_stocks(self, codes: list[str]) -> bool:
        """종목 리스트 실시간 구독 해지 (기본 구현: 미지원)"""
        return False

    async def send_message(self, payload: dict) -> bool:
        """WebSocket 송신 API (기본 구현: 미지원)"""
        return False
