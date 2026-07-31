# -*- coding: utf-8 -*-
"""
Broker Connector — 추상 브로커 커넥터 인터페이스

하이브리드 증권사 지원을 위한 추상 클래스.
구현 방식:
  - 폴링 방식: receive() 메서드 구현
  - 콜백 방식: set_message_callback() 지원

WS 콜백 인프라(_on_ws_message, set_message_callback, set_reconnect_success_callback,
_on_socket_disconnect, _make_queue_callback)는 공통 구현을 제공 —
서브클래스는 __init__에서 _receive_callback/_on_reconnect_success/_ws_queue/
_reconnecting/_stop_reconnect/_connected 를 초기화하고 _reconnect_loop()를 구현.
"""
from __future__ import annotations
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from collections.abc import Callable

logger = logging.getLogger(__name__)


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
        """재연결 루프 — 서브클래스에서 구현 (지수 백오프, 구독 복원)."""
        raise NotImplementedError("WS 커넥터는 _reconnect_loop()를 구현해야 합니다")

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
                    logger.warning("[연결] %s 데이터 큐 누락 발생 — 최신 데이터 유지", _display)
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
