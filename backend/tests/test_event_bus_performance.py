# -*- coding: utf-8 -*-
"""
Event Bus 성능 테스트 - Phase 1.3+1.4 단계 1.6
Coalescing OFF vs ON 지연 시간 비교 및 고빈도 틱 시뮬레이션
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import asyncio
import time
from typing import List

from app.core.events import (
    BrokerType,
    EventType,
    create_market_tick_event,
)
from app.core.event_bus import EventBus


class TestEventBusPerformance:
    """Event Bus 성능 테스트"""

    @pytest_asyncio.fixture
    async def event_bus(self):
        """Event Bus fixture"""
        bus = EventBus()
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_coalescing_off_vs_on_latency(self, event_bus):
        """Coalescing OFF vs ON 전체 지연 시간 비교 테스트"""
        received_events = []
        total_latencies = []
        
        async def handler(event):
            received_events.append(event)
            if hasattr(event, '_ws_receive_timestamp') and event._ws_receive_timestamp > 0:
                total_latency_ms = (event._handler_complete_timestamp - event._ws_receive_timestamp) * 1000
                total_latencies.append(total_latency_ms)
        
        # Coalescing OFF 테스트
        event_bus.disable_coalescing()
        event_bus.subscribe(EventType.MARKET_TICK, handler)
        
        # 100개 이벤트 발행
        for i in range(100):
            event = create_market_tick_event(
                broker=BrokerType.KIWOOM,
                code="005930",
                price=80000 + i,
                change=1000 + i,
                change_rate=1.25,
                volume=1000000,
                trade_amount=80000000000,
                sign="2",
                raw_data={"values": {}, "_ws_receive_timestamp": time.perf_counter()},
            )
            await event_bus.publish(event)
            await asyncio.sleep(0.001)  # 1ms 간격
        
        await asyncio.sleep(0.5)  # 처리 대기
        
        off_avg_latency = sum(total_latencies) / len(total_latencies) if total_latencies else 0
        off_coalescing_rate = event_bus.get_metrics()["coalescing_rate"]
        
        # 초기화
        received_events.clear()
        total_latencies.clear()
        event_bus._event_count = 0
        event_bus._coalescing_applied_count = 0
        event_bus._total_queue_wait_ms = 0.0
        event_bus._total_dispatch_latency_ms = 0.0
        event_bus._total_handler_latency_ms = 0.0
        
        # Coalescing ON 테스트
        event_bus.enable_coalescing()
        
        # 100개 이벤트 발행 (동일 종목)
        for i in range(100):
            event = create_market_tick_event(
                broker=BrokerType.KIWOOM,
                code="005930",
                price=80000 + i,
                change=1000 + i,
                change_rate=1.25,
                volume=1000000,
                trade_amount=80000000000,
                sign="2",
                raw_data={"values": {}, "_ws_receive_timestamp": time.perf_counter()},
            )
            await event_bus.publish(event)
            await asyncio.sleep(0.001)  # 1ms 간격
        
        await asyncio.sleep(0.5)  # 처리 대기 (Coalescing 타이머 동작 대기)
        
        on_avg_latency = sum(total_latencies) / len(total_latencies) if total_latencies else 0
        on_coalescing_rate = event_bus.get_metrics()["coalescing_rate"]
        
        # 결과 출력
        print(f"\n=== Coalescing OFF vs ON 지연 시간 비교 ===")
        print(f"Coalescing OFF - 평균 지연 시간: {off_avg_latency:.2f}ms, Coalescing Rate: {off_coalescing_rate:.2%}")
        print(f"Coalescing ON  - 평균 지연 시간: {on_avg_latency:.2f}ms, Coalescing Rate: {on_coalescing_rate:.2%}")
        
        # 검증
        assert on_coalescing_rate > off_coalescing_rate  # Coalescing ON 시 적용 비율이 높아야 함
        assert len(received_events) > 0  # 이벤트 수신 확인

    @pytest.mark.asyncio
    async def test_high_frequency_tick_simulation(self, event_bus):
        """고빈도 틱 시뮬레이션 - Coalescing Rate 변화 추이"""
        received_events = []
        coalescing_rates = []
        
        async def handler(event):
            received_events.append(event)
        
        event_bus.enable_coalescing()
        event_bus.subscribe(EventType.MARKET_TICK, handler)
        
        # 3개 종목에 대해 고빈도 틱 시뮬레이션
        codes = ["005930", "000660", "035420"]
        
        for batch in range(5):  # 5번 반복
            received_events.clear()
            event_bus._event_count = 0
            event_bus._coalescing_applied_count = 0
            
            # 각 종목별 20개 틱 발행 (총 60개)
            for code in codes:
                for i in range(20):
                    event = create_market_tick_event(
                        broker=BrokerType.KIWOOM,
                        code=code,
                        price=80000 + i,
                        change=1000 + i,
                        change_rate=1.25,
                        volume=1000000,
                        trade_amount=80000000000,
                        sign="2",
                        raw_data={"values": {}, "_ws_receive_timestamp": time.perf_counter()},
                    )
                    await event_bus.publish(event)
                    await asyncio.sleep(0.0005)  # 0.5ms 간격 (고빈도)
            
            await asyncio.sleep(0.5)  # Coalescing 타이머 동작 대기
            
            metrics = event_bus.get_metrics()
            coalescing_rate = metrics["coalescing_rate"]
            coalescing_rates.append(coalescing_rate)
            
            print(f"Batch {batch + 1} - Coalescing Rate: {coalescing_rate:.2%}, Events: {metrics['event_count']}, Coalesced: {metrics.get('coalescing_applied_count', 0)}")
        
        # Coalescing Rate 검증
        print(f"\n=== 고빈도 틱 시뮬레이션 Coalescing Rate 추이 ===")
        for i, rate in enumerate(coalescing_rates):
            print(f"Batch {i + 1}: {rate:.2%}")
        
        # Coalescing Rate이 일정 수준 이상이어야 함
        avg_coalescing_rate = sum(coalescing_rates) / len(coalescing_rates)
        assert avg_coalescing_rate > 0.5  # 평균 50% 이상 Coalescing 적용

    @pytest.mark.asyncio
    async def test_metrics_accuracy(self, event_bus):
        """메트릭 정확성 검증 테스트"""
        received_events = []
        
        async def handler(event):
            received_events.append(event)
        
        event_bus.disable_coalescing()
        event_bus.subscribe(EventType.MARKET_TICK, handler)
        
        # 50개 이벤트 발행
        for i in range(50):
            event = create_market_tick_event(
                broker=BrokerType.KIWOOM,
                code="005930",
                price=80000 + i,
                change=1000 + i,
                change_rate=1.25,
                volume=1000000,
                trade_amount=80000000000,
                sign="2",
                raw_data={"values": {}, "_ws_receive_timestamp": time.perf_counter()},
            )
            await event_bus.publish(event)
            await asyncio.sleep(0.001)
        
        await asyncio.sleep(0.5)
        
        metrics = event_bus.get_metrics()
        
        # 메트릭 검증
        assert metrics["event_count"] == 50
        assert metrics["coalescing_rate"] == 0.0  # Coalescing OFF
        assert metrics["avg_queue_wait_ms"] >= 0
        assert metrics["avg_dispatch_latency_ms"] >= 0
        assert metrics["avg_handler_latency_ms"] >= 0
        
        print(f"\n=== 메트릭 정확성 검증 ===")
        print(f"Event Count: {metrics['event_count']}")
        print(f"Coalescing Rate: {metrics['coalescing_rate']:.2%}")
        print(f"Avg Queue Wait: {metrics['avg_queue_wait_ms']:.2f}ms")
        print(f"Avg Dispatch Latency: {metrics['avg_dispatch_latency_ms']:.2f}ms")
        print(f"Avg Handler Latency: {metrics['avg_handler_latency_ms']:.2f}ms")
