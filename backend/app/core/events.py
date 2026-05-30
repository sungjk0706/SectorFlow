from __future__ import annotations
# -*- coding: utf-8 -*-
"""
Event Model - 타입 안전한 이벤트 정의

StateManager에서 사용하는 이벤트 타입 정의.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BrokerType(Enum):
    """브로커 타입"""
    KIWOOM = "kiwoom"
    LS = "ls"


class EventType(Enum):
    """이벤트 타입"""
    ORDER_CREATED = "order_created"
    ORDER_STATUS_CHANGED = "order_status_changed"
    ORDER_FILL = "order_fill"
    POSITION_UPDATED = "position_updated"
    BALANCE_UPDATED = "balance_updated"


@dataclass
class BaseEvent:
    """기본 이벤트 클래스"""
    seq: int  # 시퀀스 번호
    broker: BrokerType  # 브로커명
    received_ts: float  # 수신 타임스탬프
    event_type: EventType  # 이벤트 타입


# ── 시퀀스 번호 생성기 ────────────────────────────────────────────────────────

class SequenceGenerator:
    """시퀀스 번호 생성기 (모듈 레벨 싱글톤)"""
    _seq: int = 0

    @classmethod
    def next(cls) -> int:
        """다음 시퀀스 번호 반환"""
        cls._seq += 1
        return cls._seq

    @classmethod
    def reset(cls) -> None:
        """시퀀스 번호 초기화 (테스트용)"""
        cls._seq = 0
