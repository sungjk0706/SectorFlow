# -*- coding: utf-8 -*-
"""
Event Bus 통합 테스트 - WS 데이터 → Event 변환 검증
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import asyncio
from unittest.mock import Mock, patch

from app.core.events import (
    BrokerType,
    EventType,
    MarketTickEvent,
    create_market_tick_event,
)
from app.core.event_bus import EventBus


class TestEventBusIntegration:
    """Event Bus 통합 테스트"""

    @pytest_asyncio.fixture
    async def event_bus(self):
        """Event Bus fixture"""
        bus = EventBus()
        await bus.start()
        yield bus
        await bus.stop()

    def test_market_tick_event_creation(self):
        """MarketTickEvent 생성 테스트"""
        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={"test": "data"},
        )
        
        assert event.event_type == EventType.MARKET_TICK
        assert event.broker == BrokerType.KIWOOM
        assert event.code == "005930"
        assert event.price == 80000
        assert event.change == 1000
        assert event.change_rate == 1.25
        assert event.volume == 1000000
        assert event.trade_amount == 80000000000
        assert event.sign == "2"
        assert event.raw_data == {"test": "data"}
        assert event.seq > 0
        assert event.received_ts > 0

    @pytest.mark.asyncio
    async def test_event_bus_publish_subscribe(self, event_bus):
        """Event Bus Publish/Subscribe 테스트"""
        received_events = []
        
        async def callback(event: MarketTickEvent):
            received_events.append(event)
        
        event_bus.subscribe(EventType.MARKET_TICK, callback)
        
        # Coalescing 비활성화 (테스트 목적)
        event_bus.disable_coalescing()
        
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
        await asyncio.sleep(0.5)  # 비동기 처리 대기
        
        assert len(received_events) == 1
        assert received_events[0].code == "005930"
        assert received_events[0].price == 80000

    @pytest.mark.asyncio
    async def test_event_bus_coalescing(self, event_bus):
        """Event Bus Coalescing 테스트"""
        received_events = []
        
        async def callback(event: MarketTickEvent):
            received_events.append(event)
        
        event_bus.subscribe(EventType.MARKET_TICK, callback)
        
        # 동일 종목 연속 이벤트 발행
        for i in range(5):
            event = create_market_tick_event(
                broker=BrokerType.KIWOOM,
                code="005930",
                price=80000 + i * 100,
                change=1000,
                change_rate=1.25,
                volume=1000000,
                trade_amount=80000000000,
                sign="2",
                raw_data={},
            )
            await event_bus.publish(event)
        
        # Coalescing Map에 있는 이벤트 발행
        await event_bus.publish_coalesced()
        await asyncio.sleep(0.5)  # 비동기 처리 대기 (시간 증가)
        
        # Coalescing으로 인해 마지막 이벤트만 수신
        assert len(received_events) == 1
        assert received_events[0].price == 80400  # 마지막 가격

    @pytest.mark.asyncio
    async def test_event_bus_priority(self, event_bus):
        """Event Bus 우선순위 테스트 - 두 이벤트 타입 모두 수신 확인"""
        received_order = []
        
        async def callback_tick(event):
            received_order.append(("tick", event.seq))
        
        async def callback_fill(event):
            received_order.append(("fill", event.seq))
        
        event_bus.subscribe(EventType.MARKET_TICK, callback_tick)
        event_bus.subscribe(EventType.ORDER_FILL, callback_fill)
        
        # Coalescing 비활성화 (테스트 목적)
        event_bus.disable_coalescing()
        
        # MarketTick 발행 (우선순위 2)
        tick_event = create_market_tick_event(
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
        await event_bus.publish(tick_event)
        
        # OrderFill 발행 (우선순위 0)
        from app.core.events import create_order_fill_event
        fill_event = create_order_fill_event(
            broker=BrokerType.KIWOOM,
            order_id="ORD001",
            stock_code="005930",
            side="buy",
            fill_quantity=10,
            fill_price=80000.0,
            raw_data={},
        )
        await event_bus.publish(fill_event)
        
        await asyncio.sleep(0.5)  # 비동기 처리 대기
        
        # 두 이벤트 모두 수신 확인
        assert len(received_order) == 2
        assert any(item[0] == "fill" for item in received_order)
        assert any(item[0] == "tick" for item in received_order)

    def test_event_bus_metrics(self, event_bus):
        """Event Bus 메트릭 테스트"""
        metrics = event_bus.get_metrics()
        
        assert "event_count" in metrics
        assert "dropped_count" in metrics
        assert "queue_size" in metrics
        assert "coalescing_map_size" in metrics
        assert "subscriber_count" in metrics
