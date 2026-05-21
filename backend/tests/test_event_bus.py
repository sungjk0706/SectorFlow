# -*- coding: utf-8 -*-
"""
Event Bus 단위 테스트
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
import asyncio

from app.core.events import (
    BrokerType,
    EventType,
    MarketTickEvent,
    OrderFillEvent,
    AccountUpdateEvent,
    create_market_tick_event,
    create_order_fill_event,
    create_account_update_event,
)
from app.core.event_bus import EventBus, PriorityEvent


class TestEventBus:
    """Event Bus 테스트"""

    @pytest_asyncio.fixture
    async def event_bus(self):
        """EventBus fixture"""
        bus = EventBus()
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_singleton(self):
        """싱글톤 패턴 확인"""
        bus1 = EventBus.get_instance()
        bus2 = EventBus.get_instance()
        assert bus1 is bus2

    @pytest.mark.asyncio
    async def test_publish_subscribe(self, event_bus):
        """이벤트 발행/구독 확인"""
        received_events = []

        async def callback(event):
            received_events.append(event)

        event_bus.subscribe(EventType.MARKET_TICK, callback)
        event_bus.disable_coalescing()  # Coalescing 비활성화

        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )

        await event_bus.publish(event)
        
        # Worker가 이벤트를 처리할 시간을 줌
        await asyncio.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0].code == "005930"
        
        event_bus.enable_coalescing()  # Coalescing 다시 활성화

    @pytest.mark.asyncio
    async def test_priority_queue(self, event_bus):
        """우선순위 큐 확인 (단순화 테스트)"""
        received_events = []

        async def callback(event):
            received_events.append(event)

        event_bus.subscribe(EventType.ORDER_FILL, callback)
        event_bus.subscribe(EventType.MARKET_TICK, callback)
        event_bus.subscribe(EventType.ACCOUNT_UPDATE, callback)
        event_bus.disable_coalescing()  # Coalescing 비활성화

        # 주문 이벤트만 발행 (우선순위 0)
        order_event = create_order_fill_event(
            broker=BrokerType.KIWOOM,
            order_id="order123",
            stock_code="005930",
            side="buy",
            fill_quantity=10,
            fill_price=80000.0,
            raw_data={},
        )

        await event_bus.publish(order_event)
        await asyncio.sleep(0.1)
        
        # 주문 이벤트 수신 확인
        assert len(received_events) == 1
        assert received_events[0].event_type == EventType.ORDER_FILL
        
        event_bus.enable_coalescing()  # Coalescing 다시 활성화

    @pytest.mark.asyncio
    async def test_coalescing(self, event_bus):
        """Coalescing 확인"""
        received_events = []

        async def callback(event):
            received_events.append(event)

        event_bus.subscribe(EventType.MARKET_TICK, callback)

        # 동일 종목 이벤트 발행 (Coalescing)
        event1 = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )
        
        event2 = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80100,
            change=1100,
            change_rate=1.35,
            volume=1100000,
            trade_amount=88110000000,
            sign="2",
            raw_data={},
        )

        await event_bus.publish(event1)
        await event_bus.publish(event2)
        
        # Coalescing된 이벤트 발행
        await event_bus.publish_coalesced()
        
        # Worker가 이벤트를 처리할 시간을 줌
        await asyncio.sleep(0.1)
        
        # Coalescing으로 인해 하나만 수신되어야 함
        assert len(received_events) == 1
        assert received_events[0].price == 80100  # 마지막 이벤트

    @pytest.mark.asyncio
    async def test_unsubscribe(self, event_bus):
        """구독 해제 확인"""
        received_events = []

        async def callback(event):
            received_events.append(event)

        event_bus.subscribe(EventType.MARKET_TICK, callback)
        event_bus.disable_coalescing()  # Coalescing 비활성화

        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )

        await event_bus.publish(event)
        await asyncio.sleep(0.1)
        
        assert len(received_events) == 1
        
        # 구독 해제
        event_bus.unsubscribe(EventType.MARKET_TICK, callback)
        
        await event_bus.publish(event)
        await asyncio.sleep(0.1)
        
        # 구독 해제 후에는 수신 안 됨
        assert len(received_events) == 1
        
        event_bus.enable_coalescing()  # Coalescing 다시 활성화

    @pytest.mark.asyncio
    async def test_metrics(self, event_bus):
        """메트릭 확인"""
        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )

        await event_bus.publish(event)
        
        metrics = event_bus.get_metrics()
        assert metrics["event_count"] == 1
        assert metrics["queue_size"] >= 0
        assert metrics["coalescing_map_size"] == 1  # Coalescing Map에 있음

    @pytest.mark.asyncio
    async def test_enable_disable_coalescing(self, event_bus):
        """Coalescing 활성화/비활성화 확인"""
        event_bus.disable_coalescing()
        
        received_events = []

        async def callback(event):
            received_events.append(event)

        event_bus.subscribe(EventType.MARKET_TICK, callback)

        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )

        await event_bus.publish(event)
        await asyncio.sleep(0.1)
        
        # Coalescing 비활성화 시 즉시 수신
        assert len(received_events) == 1
        
        event_bus.enable_coalescing()


class TestPriorityEvent:
    """PriorityEvent 테스트"""

    def test_ordering(self):
        """우선순위 정렬 확인"""
        from app.core.events import create_market_tick_event, create_order_fill_event
        
        event1 = create_order_fill_event(
            broker=BrokerType.KIWOOM,
            order_id="order123",
            stock_code="005930",
            side="buy",
            fill_quantity=10,
            fill_price=80000.0,
            raw_data={},
        )
        
        event2 = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )
        
        priority1 = PriorityEvent(priority=0, event=event1)
        priority2 = PriorityEvent(priority=2, event=event2)
        
        # priority1이 더 낮으므로 먼저 나와야 함
        assert priority1 < priority2
