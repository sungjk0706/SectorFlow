# -*- coding: utf-8 -*-
"""
Event Bus - Publish-Subscribe 패턴 이벤트 라우팅

브로커에서 들어오는 이벤트를 Subscriber들에게 라우팅.
Priority Queue로 중요 이벤트 우선 처리.
Coalescing 지원 (동일 종목 이벤트 덮어쓰기).
"""
from __future__ import annotations

import asyncio
import heapq
import logging
import time
from typing import Callable, Dict, Optional, Set, Any
from dataclasses import dataclass, field

from app.core.events import BaseEvent, EventType, BrokerType

logger = logging.getLogger(__name__)


# ── Priority Queue Item ─────────────────────────────────────────────────────

@dataclass(order=True)
class PriorityEvent:
    """우선순위 큐 아이템"""
    priority: int  # 낮을수록 높은 우선순위
    event: BaseEvent = field(compare=False)


# ── Event Bus ────────────────────────────────────────────────────────────────

class EventBus:
    """
    Event Bus - Publish-Subscribe 패턴
    
    특징:
    - Priority Queue로 중요 이벤트 우선 처리
    - Coalescing 지원 (동일 종목 이벤트 덮어쓰기)
    - 비동기 Subscriber 처리
    - 이벤트 순서 보장 (시퀀스 번호)
    """

    _instance: Optional["EventBus"] = None

    def __init__(self):
        # Priority Queue
        self._priority_queue: list[PriorityEvent] = []
        self._queue_lock_obj: Optional[asyncio.Lock] = None
        
        # Coalescing Map (종목코드 -> 이벤트)
        self._coalescing_map: Dict[str, BaseEvent] = {}
        self._coalescing_enabled = True
        
        # Coalescing 파라미터 (Phase 1.3+1.4 단계 1.6)
        self._coalescing_window_ms = 50  # Coalescing 시간 윈도우 (밀리초)
        self._coalescing_max_events = 10  # 윈도우 내 최대 이벤트 수
        self._coalescing_timer_interval_ms = 10  # Coalescing 타이머 간격
        self._coalescing_timer_task: Optional[asyncio.Task] = None
        self._coalescing_map_lock_obj: Optional[asyncio.Lock] = None  # 원자성 보장
        
        # Subscribers (EventType -> Set[Callable])
        self._subscribers: Dict[EventType, Set[Callable]] = {}

        # Worker 상태
        self._is_running = False
        self._worker_task: Optional[asyncio.Task] = None
        
        # 메트릭 (Phase 1.3+1.4 단계 1.6)
        self._event_count = 0
        self._dropped_count = 0
        self._total_queue_wait_ms = 0.0
        self._total_dispatch_latency_ms = 0.0
        self._total_handler_latency_ms = 0.0
        self._coalescing_applied_count = 0

    @property
    def _queue_lock(self) -> asyncio.Lock:
        if self._queue_lock_obj is None:
            self._queue_lock_obj = asyncio.Lock()
        return self._queue_lock_obj

    @property
    def _coalescing_map_lock(self) -> asyncio.Lock:
        if self._coalescing_map_lock_obj is None:
            self._coalescing_map_lock_obj = asyncio.Lock()
        return self._coalescing_map_lock_obj

    @classmethod
    def get_instance(cls) -> "EventBus":
        """싱글톤 인스턴스 반환"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        """Event Bus 시작"""
        if self._is_running:
            logger.warning("[EventBus] 이미 실행 중")
            return

        self._is_running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        
        # Coalescing 타이머 시작 (Phase 1.3+1.4 단계 1.6)
        if self._coalescing_enabled:
            self._coalescing_timer_task = asyncio.create_task(self._coalescing_timer_loop())
        
        logger.info("[EventBus] 시작")

    async def stop(self) -> None:
        """Event Bus 중지"""
        if not self._is_running:
            return

        self._is_running = False
        
        # Coalescing 타이머 중지 (Phase 1.3+1.4 단계 1.6)
        if self._coalescing_timer_task:
            self._coalescing_timer_task.cancel()
            try:
                await self._coalescing_timer_task
            except asyncio.CancelledError:
                pass
        
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("[EventBus] 중지")

    async def publish(self, event: BaseEvent) -> None:
        """
        이벤트 발행
        
        Args:
            event: 발행할 이벤트
        """
        self._event_count += 1
        
        # 타임스탬프 추가 (Phase 1.3+1.4 단계 1.6 - 포인트 B)
        event._publish_timestamp = time.perf_counter()
        
        # Coalescing (MarketTickEvent만)
        if self._coalescing_enabled and event.event_type == EventType.MARKET_TICK:
            code = getattr(event, "code", "")
            if code:
                # 동일 종목 이벤트 덮어쓰기 (Phase 1.3+1.4 단계 1.6 - 타이머 기반)
                async with self._coalescing_map_lock:
                    self._coalescing_map[code] = event
                    self._coalescing_applied_count += 1
                logger.debug(f"[EventBus] Coalescing: {code} 이벤트 덮어쓰기")
                return
        
        # 우선순위 결정
        priority = self._get_priority(event)
        
        # Priority Queue에 추가
        async with self._queue_lock:
            heapq.heappush(self._priority_queue, PriorityEvent(priority, event))
        
        logger.debug(f"[EventBus] 이벤트 발행: {event.event_type.value} (seq={event.seq})")

    async def publish_coalesced(self) -> None:
        """Coalescing Map에 있는 이벤트 발행"""
        if not self._coalescing_map:
            return
        
        events = list(self._coalescing_map.values())
        self._coalescing_map.clear()
        
        for event in events:
            priority = self._get_priority(event)
            async with self._queue_lock:
                heapq.heappush(self._priority_queue, PriorityEvent(priority, event))
        
        logger.debug(f"[EventBus] Coalescing된 {len(events)}개 이벤트 발행")

    def subscribe(self, event_type: EventType, callback: Callable) -> None:
        """
        이벤트 구독
        
        Args:
            event_type: 구독할 이벤트 타입
            callback: 콜백 함수 (async def callback(event: BaseEvent) -> None)
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = set()
        self._subscribers[event_type].add(callback)
        logger.info(f"[EventBus] 구독 등록: {event_type.value}")

    def unsubscribe(self, event_type: EventType, callback: Callable) -> None:
        """
        이벤트 구독 해제
        
        Args:
            event_type: 구독 해제할 이벤트 타입
            callback: 콜백 함수
        """
        if event_type in self._subscribers:
            self._subscribers[event_type].discard(callback)
            logger.info(f"[EventBus] 구독 해제: {event_type.value}")

    def _get_priority(self, event: BaseEvent) -> int:
        """
        이벤트 우선순위 결정
        
        Args:
            event: 이벤트
            
        Returns:
            우선순위 (낮을수록 높은 우선순위)
        """
        # 주문/체결 이벤트: 최우선 (0)
        if event.event_type in (EventType.ORDER_FILL, EventType.ORDER_CREATED, EventType.ORDER_STATUS_CHANGED):
            return 0
        # 계좌 업데이트: 우선 (1)
        elif event.event_type == EventType.ACCOUNT_UPDATE:
            return 1
        # 시세 틱: 일반 (2)
        elif event.event_type == EventType.MARKET_TICK:
            return 2
        # 기타: 낮은 우선순위 (3)
        else:
            return 3

    async def _worker_loop(self) -> None:
        """이벤트 처리 Worker 루프"""
        try:
            while self._is_running:
                # Priority Queue에서 이벤트 가져오기
                async with self._queue_lock:
                    if not self._priority_queue:
                        await asyncio.sleep(0.001)  # CPU 절약
                        continue
                    
                    priority_event = heapq.heappop(self._priority_queue)
                    event = priority_event.event
                
                # 타임스탬프 기록 (Phase 1.3+1.4 단계 1.6 - 포인트 C)
                dispatch_start = time.perf_counter()
                if hasattr(event, '_publish_timestamp'):
                    queue_wait_ms = (dispatch_start - event._publish_timestamp) * 1000
                    self._total_queue_wait_ms += queue_wait_ms
                
                # Subscriber들에게 전달
                await self._dispatch_event(event)
                
                # 디스패치 지연 시간 기록 (Phase 1.3+1.4 단계 1.6)
                dispatch_end = time.perf_counter()
                dispatch_latency_ms = (dispatch_end - dispatch_start) * 1000
                self._total_dispatch_latency_ms += dispatch_latency_ms
                
        except asyncio.CancelledError:
            logger.info("[EventBus] Worker 취소됨")
        except Exception as e:
            logger.error(f"[EventBus] Worker 오류: {e}", exc_info=True)

    async def _dispatch_event(self, event: BaseEvent) -> None:
        """
        이벤트를 Subscriber들에게 전달
        
        Args:
            event: 전달할 이벤트
        """
        event_type = event.event_type
        subscribers = self._subscribers.get(event_type, set())
        
        if not subscribers:
            logger.debug(f"[EventBus] {event_type.value}에 대한 Subscriber 없음")
            return
        
        # 핸들러 처리 시간 측정 (Phase 1.3+1.4 단계 1.6)
        handler_start = time.perf_counter()
        
        # 비동기로 모든 Subscriber에게 전달
        tasks = []
        for callback in subscribers:
            try:
                task = asyncio.create_task(callback(event))
                tasks.append(task)
            except Exception as e:
                logger.error(f"[EventBus] 콜백 실행 실패: {e}", exc_info=True)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # 핸들러 처리 시간 기록 (Phase 1.3+1.4 단계 1.6)
        handler_end = time.perf_counter()
        handler_latency_ms = (handler_end - handler_start) * 1000
        self._total_handler_latency_ms += handler_latency_ms

    def get_metrics(self) -> Dict[str, Any]:
        """메트릭 반환 (Phase 1.3+1.4 단계 1.6 확장)"""
        avg_queue_wait_ms = (self._total_queue_wait_ms / self._event_count) if self._event_count > 0 else 0
        avg_dispatch_latency_ms = (self._total_dispatch_latency_ms / self._event_count) if self._event_count > 0 else 0
        avg_handler_latency_ms = (self._total_handler_latency_ms / self._event_count) if self._event_count > 0 else 0
        coalescing_rate = (self._coalescing_applied_count / self._event_count) if self._event_count > 0 else 0
        
        return {
            "event_count": self._event_count,
            "dropped_count": self._dropped_count,
            "queue_size": len(self._priority_queue),
            "coalescing_map_size": len(self._coalescing_map),
            "subscriber_count": sum(len(subs) for subs in self._subscribers.values()),
            "avg_queue_wait_ms": avg_queue_wait_ms,
            "avg_dispatch_latency_ms": avg_dispatch_latency_ms,
            "avg_handler_latency_ms": avg_handler_latency_ms,
            "coalescing_rate": coalescing_rate,
            "coalescing_applied_count": self._coalescing_applied_count,
        }

    def enable_coalescing(self) -> None:
        """Coalescing 활성화"""
        self._coalescing_enabled = True
        logger.info("[EventBus] Coalescing 활성화")

    def disable_coalescing(self) -> None:
        """Coalescing 비활성화"""
        self._coalescing_enabled = False
        logger.info("[EventBus] Coalescing 비활성화")

    async def _coalescing_timer_loop(self) -> None:
        """Coalescing 타이머 루프 (Phase 1.3+1.4 단계 1.6)"""
        try:
            while self._is_running:
                await asyncio.sleep(self._coalescing_timer_interval_ms / 1000)
                
                # Coalescing Map에서 이벤트 발행 (참조 교체로 원자성 보장)
                async with self._coalescing_map_lock:
                    if not self._coalescing_map:
                        continue
                    
                    # 참조 교체 (Swap)
                    events_to_publish = self._coalescing_map.copy()
                    self._coalescing_map.clear()
                
                # 발행
                for event in events_to_publish.values():
                    priority = self._get_priority(event)
                    async with self._queue_lock:
                        heapq.heappush(self._priority_queue, PriorityEvent(priority, event))
                
                logger.debug(f"[EventBus] Coalescing 타이머: {len(events_to_publish)}개 이벤트 발행")
                
        except asyncio.CancelledError:
            logger.info("[EventBus] Coalescing 타이머 취소됨")
        except Exception as e:
            logger.error(f"[EventBus] Coalescing 타이머 오류: {e}", exc_info=True)
