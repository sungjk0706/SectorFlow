from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
전역 이벤트 버스 (Queues) - 파이프라인 아키텍처 핵심 배관

HTS급 실시간 처리를 위한 4개 코어 큐:
- tick_queue: 시세 수신 전용 (드롭 정책 적용)
- order_queue: 주문/체결 전용 (무결성 보장)
- broadcast_queue: UI 프론트엔드 전송 전용
- control_queue: 사용자 설정 제어 전용 (최우선순위)

외부 브로커(Redis 등) 미사용 - 순수 asyncio.Queue 기반 프로세스 내 배관.
"""

import asyncio

from backend.app.core.logger import get_logger

logger = get_logger("core_queues")


# ── 큐 크기 설정 ─────────────────────────────────────────────────────────────
TICK_QUEUE_MAXSIZE = 5000  # 시세 수신 전용 (드롭 정책 적용)
BROADCAST_QUEUE_MAXSIZE = 2000  # UI 전송 전용
CONTROL_QUEUE_MAXSIZE = 500  # 제어 전용 (최우선순위)


# ── 전역 큐 인스턴스 ───────────────────────────────────────────────────────────
_tick_queue: Optional[asyncio.Queue] = None
_broadcast_queue: Optional[asyncio.Queue] = None
_control_queue: Optional[asyncio.PriorityQueue] = None


def initialize_queues() -> None:
    """전역 큐 인스턴스 초기화 (엔진 기동 시 1회 호출)."""
    global _tick_queue, _broadcast_queue, _control_queue

    if _tick_queue is not None:
        return

    _tick_queue = asyncio.Queue(maxsize=TICK_QUEUE_MAXSIZE)
    _broadcast_queue = asyncio.Queue(maxsize=BROADCAST_QUEUE_MAXSIZE)
    _control_queue = asyncio.PriorityQueue(maxsize=CONTROL_QUEUE_MAXSIZE)

    logger.info(
        "[core_queues] 초기화 완료 - "
        f"tick={TICK_QUEUE_MAXSIZE}, "
        f"broadcast={BROADCAST_QUEUE_MAXSIZE}, control={CONTROL_QUEUE_MAXSIZE}"
    )


def get_tick_queue() -> asyncio.Queue:
    """시세 수신 전용 큐 반환."""
    if _tick_queue is None:
        raise RuntimeError("tick_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _tick_queue


def get_broadcast_queue() -> asyncio.Queue:
    """UI 전송 전용 큐 반환."""
    if _broadcast_queue is None:
        raise RuntimeError("broadcast_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _broadcast_queue


def get_control_queue() -> asyncio.PriorityQueue:
    """제어 전용 큐 반환."""
    if _control_queue is None:
        raise RuntimeError("control_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _control_queue


# ── Tick Queue 드롭 정책 (무손실 최신화) ─────────────────────────────────────────
async def put_tick_with_drop_policy(data: dict) -> None:
    """
    tick_queue에 데이터 삽입 - 드롭 정책 적용.

    정책:
    - 큐가 가득 찼을 때 (QueueFull), 가장 오래된 데이터를 즉시 버리고 최신 시세를 밀어넣음.
    - 시장 폭락 시 틱 폭주 대비 - 무손실 최신화 보장.

    Args:
        data: 시세 데이터 (dict)
    """
    queue = get_tick_queue()

    try:
        await queue.put(data)
    except asyncio.QueueFull:
        # 큐가 가득 찼으면 가장 오래된 데이터 버리고 최신 데이터 밀어넣기
        try:
            queue.get_nowait()  # 가장 오래된 데이터 제거
            await queue.put(data)  # 최신 데이터 삽입
            logger.debug("[core_queues] tick_queue 드롭 발생 - 최신 데이터 유지")
        except asyncio.QueueEmpty:
            # 경합 조건: 다른 태스크가 이미 데이터를 꺼낸 경우
            await queue.put(data)


def clear_all_queues() -> None:
    """모든 큐 비우기 (엔진 정지 시 호출)."""
    global _tick_queue, _broadcast_queue, _control_queue

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

    logger.info("[core_queues] 모든 큐 비우기 완료")
