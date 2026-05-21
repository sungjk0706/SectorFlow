# -*- coding: utf-8 -*-
"""
Event Model - 타입 안전한 이벤트 정의

브로커(Kiwoom/LS)에서 들어오는 실시간 데이터를 규격화된 이벤트로 변환.
Pydantic 모델을 사용하여 타입 안전성 확보.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
import time


class BrokerType(Enum):
    """브로커 타입"""
    KIWOOM = "kiwoom"
    LS = "ls"


class EventType(Enum):
    """이벤트 타입"""
    MARKET_TICK = "market_tick"
    ORDER_FILL = "order_fill"
    ACCOUNT_UPDATE = "account_update"
    ORDER_CREATED = "order_created"
    ORDER_STATUS_CHANGED = "order_status_changed"
    POSITION_UPDATED = "position_updated"
    BALANCE_UPDATED = "balance_updated"


@dataclass
class BaseEvent:
    """기본 이벤트 클래스"""
    seq: int  # 시퀀스 번호
    broker: BrokerType  # 브로커명
    received_ts: float  # 수신 타임스탬프
    event_type: EventType  # 이벤트 타입


@dataclass
class MarketTickEvent(BaseEvent):
    """시세 틱 이벤트"""
    code: str  # 종목코드
    price: int  # 현재가
    change: int  # 전일대비
    change_rate: float  # 등락률
    volume: int  # 거래량
    trade_amount: int  # 거래대금
    sign: str  # "1"상한 "2"상승 "3"보합 "4"하한 "5"하락
    prev_close: int = 0  # 전일종가
    strength: str = "-"  # 체결강도
    # 추가 메타데이터
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderFillEvent(BaseEvent):
    """주문 체결 이벤트"""
    order_id: str  # 주문ID
    stock_code: str  # 종목코드
    side: str  # "buy" or "sell"
    fill_quantity: int  # 체결수량
    fill_price: float  # 체결가
    broker_order_id: Optional[str] = None  # 증권사 주문번호
    # 추가 메타데이터
    raw_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AccountUpdateEvent(BaseEvent):
    """계좌 업데이트 이벤트"""
    deposit: int  # 예수금
    orderable: int  # 주문가능금액
    total_eval_amount: int  # 총평가금액
    total_pnl: int  # 총평가손익
    total_pnl_rate: float  # 총수익률
    position_count: int  # 보유종목수
    # 추가 메타데이터
    raw_data: Dict[str, Any] = field(default_factory=dict)


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


def create_market_tick_event(
    broker: BrokerType,
    code: str,
    price: int,
    change: int,
    change_rate: float,
    volume: int,
    trade_amount: int,
    sign: str,
    raw_data: Dict[str, Any],
    prev_close: int = 0,
    strength: str = "-",
) -> MarketTickEvent:
    """MarketTickEvent 생성 헬퍼"""
    return MarketTickEvent(
        seq=SequenceGenerator.next(),
        broker=broker,
        received_ts=time.time(),
        event_type=EventType.MARKET_TICK,
        code=code,
        price=price,
        change=change,
        change_rate=change_rate,
        volume=volume,
        trade_amount=trade_amount,
        sign=sign,
        prev_close=prev_close,
        strength=strength,
        raw_data=raw_data,
    )


def create_order_fill_event(
    broker: BrokerType,
    order_id: str,
    stock_code: str,
    side: str,
    fill_quantity: int,
    fill_price: float,
    raw_data: Dict[str, Any],
    broker_order_id: Optional[str] = None,
) -> OrderFillEvent:
    """OrderFillEvent 생성 헬퍼"""
    return OrderFillEvent(
        seq=SequenceGenerator.next(),
        broker=broker,
        received_ts=time.time(),
        event_type=EventType.ORDER_FILL,
        order_id=order_id,
        stock_code=stock_code,
        side=side,
        fill_quantity=fill_quantity,
        fill_price=fill_price,
        broker_order_id=broker_order_id,
        raw_data=raw_data,
    )


def create_account_update_event(
    broker: BrokerType,
    deposit: int,
    orderable: int,
    total_eval_amount: int,
    total_pnl: int,
    total_pnl_rate: float,
    position_count: int,
    raw_data: Dict[str, Any],
) -> AccountUpdateEvent:
    """AccountUpdateEvent 생성 헬퍼"""
    return AccountUpdateEvent(
        seq=SequenceGenerator.next(),
        broker=broker,
        received_ts=time.time(),
        event_type=EventType.ACCOUNT_UPDATE,
        deposit=deposit,
        orderable=orderable,
        total_eval_amount=total_eval_amount,
        total_pnl=total_pnl,
        total_pnl_rate=total_pnl_rate,
        position_count=position_count,
        raw_data=raw_data,
    )
