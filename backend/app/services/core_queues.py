# -*- coding: utf-8 -*-
"""
전역 이벤트 버스 (큐) - 파이프라인 아키텍처 핵심 배관

HTS급 실시간 처리를 위한 4개 코어 큐:
- tick_queue: 시세 수신 전용 (누락 정책 적용)
- broadcast_queue: 화면 전송 전용
- control_queue: 사용자 설정 제어 전용 (최우선순위)
- order_queue: 주문 실행 요청 전용 (매도 조건 검사·매수 후보 평가 요청을 시세/업종 루프에서 주문 실행 루프로 전달)

외부 브로커(Redis 등) 미사용 - 순수 asyncio.Queue 기반 프로세스 내 배관.
"""
from __future__ import annotations
from typing import Optional
import asyncio
import logging
logger = logging.getLogger(__name__)


# ── 큐 크기 설정 ─────────────────────────────────────────────────────────────
TICK_QUEUE_MAXSIZE = 20000  # 시세 수신 전용 (누락 정책 적용)
BROADCAST_QUEUE_MAXSIZE = 2000  # 화면 전송 전용
CONTROL_QUEUE_MAXSIZE = 500  # 제어 전용 (최우선순위)
ORDER_QUEUE_MAXSIZE = 100  # 주문 실행 요청 전용 (매도 조건 검사·매수 후보 평가)


# ── 전역 큐 인스턴스 ───────────────────────────────────────────────────────────
_tick_queue: Optional[asyncio.Queue] = None
_broadcast_queue: Optional[asyncio.Queue] = None
_control_queue: Optional[asyncio.PriorityQueue] = None
_order_queue: Optional[asyncio.Queue] = None


def initialize_queues() -> None:
    """전역 큐 인스턴스 초기화 (엔진 기동 시 1회 호출)."""
    global _tick_queue, _broadcast_queue, _control_queue, _order_queue

    if _tick_queue is not None:
        return

    _tick_queue = asyncio.Queue(maxsize=TICK_QUEUE_MAXSIZE)
    _broadcast_queue = asyncio.Queue(maxsize=BROADCAST_QUEUE_MAXSIZE)
    _control_queue = asyncio.PriorityQueue(maxsize=CONTROL_QUEUE_MAXSIZE)
    _order_queue = asyncio.Queue(maxsize=ORDER_QUEUE_MAXSIZE)

    logger.info(
        "[시스템] 초기화 완료 - "
        f"시세={TICK_QUEUE_MAXSIZE}, "
        f"전송={BROADCAST_QUEUE_MAXSIZE}, 제어={CONTROL_QUEUE_MAXSIZE}, "
        f"주문={ORDER_QUEUE_MAXSIZE}"
    )


def get_tick_queue() -> asyncio.Queue:
    """시세 수신 전용 큐 반환."""
    if _tick_queue is None:
        raise RuntimeError("tick_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _tick_queue


def get_broadcast_queue() -> asyncio.Queue:
    """화면 전송 전용 큐 반환."""
    if _broadcast_queue is None:
        raise RuntimeError("broadcast_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _broadcast_queue


def get_control_queue() -> asyncio.PriorityQueue:
    """제어 전용 큐 반환."""
    if _control_queue is None:
        raise RuntimeError("control_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _control_queue


def get_order_queue() -> asyncio.Queue:
    """주문 실행 요청 전용 큐 반환."""
    if _order_queue is None:
        raise RuntimeError("order_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _order_queue


def clear_all_queues() -> None:
    """모든 큐 비우기 (엔진 정지 시 호출)."""
    if _tick_queue:
        while not _tick_queue.empty():
            _tick_queue.get_nowait()
    if _broadcast_queue:
        while not _broadcast_queue.empty():
            _broadcast_queue.get_nowait()
    if _control_queue:
        while not _control_queue.empty():
            try:
                _, _, _ = _control_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    if _order_queue:
        while not _order_queue.empty():
            _order_queue.get_nowait()

    logger.info("[시스템] 모든 큐 비우기")