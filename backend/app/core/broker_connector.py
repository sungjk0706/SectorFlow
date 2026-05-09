# -*- coding: utf-8 -*-
"""
Broker Connector — 추상 브로커 커넥터 인터페이스

하이브리드 증권사 지원을 위한 추상 클래스.
구현 방식:
  - 폴링 방식: receive() 메서드 구현
  - 콜백 방식: set_message_callback() 지원
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable


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
    
    @property
    @abstractmethod
    def broker_id(self) -> str:
        """증권사 식별자 (예: 'kiwoom', 'ls')"""
        ...
    
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
    
    @abstractmethod
    async def unsubscribe(self, code: str, data_types: list[str]) -> bool:
        """종목 구독 해지"""
        ...
    
    async def receive(self) -> DataMessage | None:
        """데이터 수신 (블로킹) — 폴링 방식 커넥터용"""
        raise NotImplementedError("폴링 방식 커넥터는 receive()를 구현해야 합니다")
    
    def set_message_callback(self, callback: Callable[[dict], None]) -> None:
        """메시지 수신 콜백 설정 — 콜백 방식 커넥터용
        
        UnifiedWSManager가 자동으로 호출합니다.
        """
        pass  # 콜백 방식 커넥터는 오버라이드
    
    @abstractmethod
    def is_connected(self) -> bool:
        """연결 상태 확인"""
        ...
