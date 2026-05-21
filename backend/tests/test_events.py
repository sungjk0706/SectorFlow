# -*- coding: utf-8 -*-
"""
Event Model 단위 테스트
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.events import (
    BrokerType,
    EventType,
    MarketTickEvent,
    OrderFillEvent,
    AccountUpdateEvent,
    SequenceGenerator,
    create_market_tick_event,
    create_order_fill_event,
    create_account_update_event,
)


class TestSequenceGenerator:
    """시퀀스 번호 생성기 테스트"""

    def test_next_increments(self):
        """시퀀스 번호가 증가하는지 확인"""
        SequenceGenerator.reset()
        assert SequenceGenerator.next() == 1
        assert SequenceGenerator.next() == 2
        assert SequenceGenerator.next() == 3

    def test_reset(self):
        """시퀀스 번호 초기화 확인"""
        SequenceGenerator.next()
        SequenceGenerator.next()
        SequenceGenerator.reset()
        assert SequenceGenerator.next() == 1


class TestMarketTickEvent:
    """MarketTickEvent 테스트"""

    def test_creation(self):
        """MarketTickEvent 생성 확인"""
        event = MarketTickEvent(
            seq=1,
            broker=BrokerType.KIWOOM,
            received_ts=1234567890.0,
            event_type=EventType.MARKET_TICK,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
        )
        assert event.seq == 1
        assert event.broker == BrokerType.KIWOOM
        assert event.code == "005930"
        assert event.price == 80000
        assert event.change == 1000
        assert event.change_rate == 1.25
        assert event.volume == 1000000
        assert event.trade_amount == 80000000000
        assert event.sign == "2"

    def test_helper_function(self):
        """create_market_tick_event 헬퍼 함수 확인"""
        SequenceGenerator.reset()
        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={"raw": "data"},
        )
        assert event.seq == 1
        assert event.broker == BrokerType.KIWOOM
        assert event.code == "005930"
        assert event.raw_data == {"raw": "data"}


class TestOrderFillEvent:
    """OrderFillEvent 테스트"""

    def test_creation(self):
        """OrderFillEvent 생성 확인"""
        event = OrderFillEvent(
            seq=1,
            broker=BrokerType.KIWOOM,
            received_ts=1234567890.0,
            event_type=EventType.ORDER_FILL,
            order_id="order123",
            stock_code="005930",
            side="buy",
            fill_quantity=10,
            fill_price=80000.0,
        )
        assert event.seq == 1
        assert event.broker == BrokerType.KIWOOM
        assert event.order_id == "order123"
        assert event.stock_code == "005930"
        assert event.side == "buy"
        assert event.fill_quantity == 10
        assert event.fill_price == 80000.0

    def test_helper_function(self):
        """create_order_fill_event 헬퍼 함수 확인"""
        SequenceGenerator.reset()
        event = create_order_fill_event(
            broker=BrokerType.KIWOOM,
            order_id="order123",
            stock_code="005930",
            side="buy",
            fill_quantity=10,
            fill_price=80000.0,
            raw_data={"raw": "data"},
            broker_order_id="broker_order_123",
        )
        assert event.seq == 1
        assert event.broker == BrokerType.KIWOOM
        assert event.order_id == "order123"
        assert event.broker_order_id == "broker_order_123"
        assert event.raw_data == {"raw": "data"}


class TestAccountUpdateEvent:
    """AccountUpdateEvent 테스트"""

    def test_creation(self):
        """AccountUpdateEvent 생성 확인"""
        event = AccountUpdateEvent(
            seq=1,
            broker=BrokerType.KIWOOM,
            received_ts=1234567890.0,
            event_type=EventType.ACCOUNT_UPDATE,
            deposit=100000000,
            orderable=50000000,
            total_eval_amount=150000000,
            total_pnl=50000000,
            total_pnl_rate=50.0,
            position_count=5,
        )
        assert event.seq == 1
        assert event.broker == BrokerType.KIWOOM
        assert event.deposit == 100000000
        assert event.orderable == 50000000
        assert event.total_eval_amount == 150000000
        assert event.total_pnl == 50000000
        assert event.total_pnl_rate == 50.0
        assert event.position_count == 5

    def test_helper_function(self):
        """create_account_update_event 헬퍼 함수 확인"""
        SequenceGenerator.reset()
        event = create_account_update_event(
            broker=BrokerType.KIWOOM,
            deposit=100000000,
            orderable=50000000,
            total_eval_amount=150000000,
            total_pnl=50000000,
            total_pnl_rate=50.0,
            position_count=5,
            raw_data={"raw": "data"},
        )
        assert event.seq == 1
        assert event.broker == BrokerType.KIWOOM
        assert event.deposit == 100000000
        assert event.raw_data == {"raw": "data"}


class TestEventType:
    """EventType Enum 테스트"""

    def test_market_tick(self):
        """MARKET_TICK 이벤트 타입 확인"""
        assert EventType.MARKET_TICK.value == "market_tick"

    def test_order_fill(self):
        """ORDER_FILL 이벤트 타입 확인"""
        assert EventType.ORDER_FILL.value == "order_fill"

    def test_account_update(self):
        """ACCOUNT_UPDATE 이벤트 타입 확인"""
        assert EventType.ACCOUNT_UPDATE.value == "account_update"

    def test_order_created(self):
        """ORDER_CREATED 이벤트 타입 확인"""
        assert EventType.ORDER_CREATED.value == "order_created"

    def test_order_status_changed(self):
        """ORDER_STATUS_CHANGED 이벤트 타입 확인"""
        assert EventType.ORDER_STATUS_CHANGED.value == "order_status_changed"

    def test_position_updated(self):
        """POSITION_UPDATED 이벤트 타입 확인"""
        assert EventType.POSITION_UPDATED.value == "position_updated"

    def test_balance_updated(self):
        """BALANCE_UPDATED 이벤트 타입 확인"""
        assert EventType.BALANCE_UPDATED.value == "balance_updated"


class TestBrokerType:
    """BrokerType Enum 테스트"""

    def test_kiwoom(self):
        """KIWOOM 브로커 타입 확인"""
        assert BrokerType.KIWOOM.value == "kiwoom"

    def test_ls(self):
        """LS 브로커 타입 확인"""
        assert BrokerType.LS.value == "ls"
